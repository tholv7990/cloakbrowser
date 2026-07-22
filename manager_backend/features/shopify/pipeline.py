"""Staged, idempotent, draft-only build pipeline.

`create_build_plan` re-resolves theme/preset/products/analysis and persists a
plan + one step row each — changing nothing on Shopify. `execute_build_plan`
(requires confirm) runs each step, skips already-completed ones so a partial
build re-runs safely, and turns GraphQL userErrors into step failures without
raising. The theme step duplicates into an UNPUBLISHED draft and batch-upserts
files with recursive bisection to isolate a bad file — it never publishes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import ShopifyBuildPlan, ShopifyPlanStep, ShopifyStore
from ..proxies.credentials import CredentialStore
from .clients import OpenAIImageClient, ShopifyClient, StoreContext
from .service import CATALOGS, get_ai_settings, store_context


STEP_ORDER = [
    "product_csv",
    "analysis",
    "identity",
    "content",
    "policies",
    "navigation",
    "preset",
    "design",
    "theme",
]
STEP_CAPABILITY = {
    "product_csv": "write_products",
    "content": "write_pages",
    "policies": "write_legal_policies",
    "navigation": "write_navigation",
    "theme": "write_themes",
}
_THEME_BATCH_SIZE = 50


def _store(session: Session, store_id: str) -> ShopifyStore:
    store = session.get(ShopifyStore, store_id)
    if store is None:
        raise ManagerError("store_not_found", "The requested store was not found.", 404)
    return store


def _plan(session: Session, store_id: str, plan_id: str) -> ShopifyBuildPlan:
    plan = session.get(ShopifyBuildPlan, plan_id)
    if plan is None or plan.store_id != store_id:
        raise ManagerError("plan_not_found", "The requested plan was not found.", 404)
    return plan


def build_plan_steps(capabilities: dict) -> list[tuple[str, str, str | None]]:
    """Return (key, status, reason) per step — ready or blocked, no side effects."""
    steps = []
    for key in STEP_ORDER:
        needed = STEP_CAPABILITY.get(key)
        if needed and not capabilities.get(needed):
            steps.append((key, "blocked", f"Requires the {needed} scope."))
        else:
            steps.append((key, "ready", None))
    return steps


def plan_to_dict(session: Session, plan: ShopifyBuildPlan) -> dict:
    config = dict(plan.config_json or {})
    steps = session.scalars(
        select(ShopifyPlanStep)
        .where(ShopifyPlanStep.plan_id == plan.id)
        .order_by(ShopifyPlanStep.order_index)
    ).all()
    return {
        "id": plan.id,
        "store_id": plan.store_id,
        "status": plan.status,
        "mode": plan.mode,
        "niche": config.get("niche", ""),
        "language": config.get("language", ""),
        "theme_name": config.get("theme_name", ""),
        "preset": config.get("preset", ""),
        "product_count": config.get("product_count", 0),
        "ai_hero": bool(config.get("ai_hero")),
        "admin_url": config.get("admin_url"),
        "preview_url": config.get("preview_url"),
        "created_at": plan.created_at,
        "steps": [
            {"key": s.key, "status": s.status, "reason": s.reason, "error": s.error}
            for s in steps
        ],
    }


def get_plan(session: Session, store_id: str, plan_id: str) -> dict:
    return plan_to_dict(session, _plan(session, store_id, plan_id))


def create_build_plan(session: Session, store_id: str, payload) -> dict:
    store = _store(session, store_id)
    catalog = None
    if payload.product_source == "catalog":
        catalog = next((c for c in CATALOGS if c["id"] == payload.catalog_id), None)
        if catalog is None:
            raise ManagerError("catalog_not_found", "The chosen catalog was not found.", 400)

    products = list(catalog["products"]) if catalog else []
    product_count = len(products) if catalog else (store.shop_info_json or {}).get("product_count") or 0
    niche = payload.niche_override or (catalog["niche"] if catalog else None) or store.niche or "General store"
    language = store.language or "en"
    ai = get_ai_settings(session)
    ai_hero = bool(payload.ai_hero and ai["enabled"] and ai["has_api_key"])
    theme_name = f"CloakBrowser - {store.store_name or store.shop_domain} - {payload.preset or 'Default'}"

    config = {
        "niche": niche,
        "language": language,
        "theme_id": payload.theme_id,
        "theme_name": theme_name,
        "preset": payload.preset,
        "product_source": payload.product_source,
        "product_count": product_count,
        "products": products,
        "ai_hero": ai_hero,
        "admin_url": None,
        "preview_url": None,
    }
    plan = ShopifyBuildPlan(store_id=store_id, status="staged", mode="draft_only", config_json=config)
    session.add(plan)
    session.flush()
    for order_index, (key, status, reason) in enumerate(build_plan_steps(dict(store.inspection_json or {}))):
        session.add(
            ShopifyPlanStep(
                plan_id=plan.id, key=key, status=status, reason=reason, order_index=order_index
            )
        )
    session.commit()
    session.refresh(plan)
    return plan_to_dict(session, plan)


# --- theme-file bisection (pure) --------------------------------------------
def upsert_theme_files(files: list[dict], batch_upsert, batch_size: int = _THEME_BATCH_SIZE) -> list[str]:
    """Upsert theme files in batches, liquid before json, bisecting to isolate
    a file Shopify rejects. `batch_upsert(batch)` returns the rejected keys."""
    ordered = sorted(files, key=lambda f: 0 if str(f.get("key", "")).endswith(".liquid") else 1)
    rejected: list[str] = []
    for start in range(0, len(ordered), batch_size):
        rejected += _bisect_batch(ordered[start : start + batch_size], batch_upsert)
    return rejected


def _bisect_batch(batch: list[dict], batch_upsert) -> list[str]:
    if not batch:
        return []
    if not batch_upsert(batch):
        return []
    if len(batch) == 1:
        return [batch[0]["key"]]
    middle = len(batch) // 2
    return _bisect_batch(batch[:middle], batch_upsert) + _bisect_batch(batch[middle:], batch_upsert)


# --- lean build content ------------------------------------------------------
def _product_inputs(config: dict) -> list[dict]:
    return [{"handle": p["handle"], "title": p["title"]} for p in config.get("products", [])]


def _pages(config: dict) -> list[dict]:
    return [
        {"title": "About Us", "handle": "about"},
        {"title": "FAQ", "handle": "faq"},
        {"title": "Contact", "handle": "contact"},
    ]


def _policies(config: dict) -> list[dict]:
    return [{"type": t} for t in ("REFUND_POLICY", "PRIVACY_POLICY", "TERMS_OF_SERVICE", "SHIPPING_POLICY")]


def _menus(config: dict) -> list[dict]:
    return [
        {"title": "Main menu", "handle": "main-menu", "items": []},
        {"title": "Footer", "handle": "footer", "items": []},
    ]


def _theme_files(config: dict) -> list[dict]:
    preset = config.get("preset", "Default")
    return [
        {"key": "layout/theme.liquid", "value": f"<!-- {config['theme_name']} -->", "content_type": "liquid"},
        {"key": "assets/cloak-storefront.css", "value": f"/* {preset} */", "content_type": "css"},
        {"key": "sections/cloak-storefront.liquid", "value": "<section></section>", "content_type": "liquid"},
        {"key": "templates/index.json", "value": '{"sections":{}}', "content_type": "json"},
    ]


# --- execution ---------------------------------------------------------------
def execute_build_plan(
    session: Session,
    cred_store: CredentialStore,
    shopify: ShopifyClient,
    openai: OpenAIImageClient,
    store_id: str,
    plan_id: str,
    confirm: bool,
) -> dict:
    if not confirm:
        raise ManagerError("confirm_required", "Execution must be confirmed.", 422)
    store = _store(session, store_id)
    plan = _plan(session, store_id, plan_id)
    ctx = store_context(session, cred_store, store, shopify)
    config = dict(plan.config_json or {})
    plan.status = "running"
    session.commit()

    steps = session.scalars(
        select(ShopifyPlanStep)
        .where(ShopifyPlanStep.plan_id == plan_id)
        .order_by(ShopifyPlanStep.order_index)
    ).all()
    theme_result: dict | None = None
    for step in steps:
        if step.status in {"completed", "blocked"}:
            continue  # idempotent: never re-run a finished or ungrantable step
        result = _run_plan_step(session, step, ctx, shopify, openai, config)
        if step.key == "theme" and step.status == "completed":
            theme_result = result

    if theme_result:
        config["admin_url"] = theme_result.get("admin_url")
        config["preview_url"] = theme_result.get("preview_url")
        plan.config_json = config

    runnable = [s for s in steps if s.status != "blocked"]
    failed = [s for s in runnable if s.status == "failed"]
    completed = [s for s in runnable if s.status == "completed"]
    if failed and completed:
        plan.status = "partial"
    elif failed:
        plan.status = "failed"
    else:
        plan.status = "completed"
    session.commit()
    session.refresh(plan)
    return plan_to_dict(session, plan)


def _run_plan_step(session, step, ctx, shopify, openai, config) -> dict:
    step.status = "running"
    step.attempts += 1
    step.error = None
    session.commit()
    try:
        result, user_errors = _execute_step(step.key, ctx, shopify, openai, config)
    except ManagerError as error:
        step.status = "failed"
        step.error = error.message[:1000]
        session.commit()
        return {}
    except Exception as error:  # network / unexpected — a step failure, never a 500
        step.status = "failed"
        step.error = str(error)[:1000]
        session.commit()
        return {}
    if user_errors:
        step.status = "failed"
        step.error = "; ".join(str(e) for e in user_errors)[:1000]
    else:
        step.status = "completed"
        step.result_json = result
    session.commit()
    return result


def _execute_step(key, ctx: StoreContext, shopify: ShopifyClient, openai, config) -> tuple[dict, list]:
    if key == "product_csv":
        products = _product_inputs(config)
        if not products:
            return {"skipped": "no products"}, []
        outcome = shopify.upsert_products(ctx, products)
        return {"count": outcome.get("count", 0)}, outcome.get("userErrors", [])
    if key == "analysis":
        return {"niche": config["niche"], "language": config["language"]}, []
    if key == "identity":
        return {"theme_name": config["theme_name"]}, []
    if key == "content":
        outcome = shopify.upsert_pages(ctx, _pages(config))
        return {"pages": outcome.get("count", 0)}, outcome.get("userErrors", [])
    if key == "policies":
        outcome = shopify.update_policies(ctx, _policies(config))
        return {"policies": outcome.get("count", 0)}, outcome.get("userErrors", [])
    if key == "navigation":
        outcome = shopify.upsert_menus(ctx, _menus(config))
        return {"menus": outcome.get("count", 0)}, outcome.get("userErrors", [])
    if key == "preset":
        return {"preset": config["preset"]}, []
    if key == "design":
        return {"files": len(_theme_files(config))}, []
    if key == "theme":
        new_theme_id = shopify.duplicate_theme(ctx, config["theme_id"], config["theme_name"])
        rejected = upsert_theme_files(
            _theme_files(config),
            lambda batch: shopify.upsert_theme_file_batch(ctx, new_theme_id, batch),
        )
        admin_url, preview_url = shopify.theme_urls(ctx, new_theme_id)
        errors = [f"theme file rejected: {key}" for key in rejected]
        return {"theme_id": new_theme_id, "admin_url": admin_url, "preview_url": preview_url}, errors
    return {}, []
