"""Staged, idempotent, draft-only build pipeline.

`create_build_plan` re-resolves theme/preset/products/analysis and persists a
plan + one step row each — changing nothing on Shopify. `execute_build_plan`
(requires confirm) runs each step, skips already-completed ones so a partial
build re-runs safely, and turns GraphQL userErrors into step failures without
raising. The theme step duplicates into an UNPUBLISHED draft and batch-upserts
files with recursive bisection to isolate a bad file — it never publishes.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import ShopifyBuildPlan, ShopifyPlanStep, ShopifyStore
from ..proxies.credentials import CredentialStore
from .clients import OpenAIImageClient, ShopifyClient, StoreContext
from .service import CATALOGS, get_ai_settings, store_context


_LOG = logging.getLogger("manager.shopify")


def _redact(text: str, ctx: StoreContext) -> str:
    """Strip the store token and proxy URL from any text before it is surfaced."""
    out = str(text)
    for secret in (ctx.token, ctx.proxy_url):
        if secret:
            out = out.replace(secret, "***")
    return out


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
def recover_interrupted_plans(session_factory) -> int:
    """Reset plans left 'running' by an interrupted process so they can be re-run.

    Completed steps persist, so a re-execution safely resumes and skips them. Runs
    at startup, mirroring the automation run recovery.
    """
    with session_factory() as session:
        result = session.execute(
            update(ShopifyBuildPlan)
            .where(ShopifyBuildPlan.status == "running")
            .values(status="failed")
        )
        session.commit()
        return result.rowcount


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
    # Atomically claim execution — only one runner may own a plan at a time, so a
    # concurrent execute can't double-run steps (duplicate themes/products).
    claimed = session.execute(
        update(ShopifyBuildPlan)
        .where(ShopifyBuildPlan.id == plan_id, ShopifyBuildPlan.status != "running")
        .values(status="running")
    ).rowcount
    session.commit()
    if claimed != 1:
        raise ManagerError(
            "plan_execution_in_progress", "This plan is already being executed.", 409
        )
    session.refresh(plan)
    ctx = store_context(session, cred_store, store, shopify)
    config = dict(plan.config_json or {})

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
        result, user_errors = _execute_step(session, step, ctx, shopify, openai, config)
    except ManagerError as error:
        step.status = "failed"
        step.error = error.message[:1000]  # our own fixed, safe message
        session.commit()
        return {}
    except Exception as error:  # network / unexpected — a step failure, never a 500
        # Never persist raw exception text: it can carry the token, a proxy URL, or
        # an HTTP body. Log a redacted detail; surface only a stable safe message.
        _LOG.warning("shopify step %s failed: %s", step.key, _redact(repr(error), ctx))
        step.status = "failed"
        step.error = f"The {step.key} step failed unexpectedly."
        session.commit()
        return {}
    if user_errors:
        step.status = "failed"
        step.error = _redact("; ".join(str(e) for e in user_errors), ctx)[:1000]
    else:
        step.status = "completed"
        step.result_json = result
    session.commit()
    return result


def _execute_step(session, step, ctx: StoreContext, shopify: ShopifyClient, openai, config) -> tuple[dict, list]:
    key = step.key
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
        return _run_theme_step(session, step, ctx, shopify, config)
    return {}, []


def _draft_only(role: str) -> bool:
    return str(role or "").lower() == "unpublished"


def _run_theme_step(session, step, ctx: StoreContext, shopify: ShopifyClient, config) -> tuple[dict, list]:
    """Build onto a private draft ONLY, enforced structurally.

    The duplicate must be a NEW, UNPUBLISHED theme (id != source, role == unpublished),
    and the role is re-fetched and re-checked before EVERY file batch — so we never
    write to the live/main theme even if it flips mid-build. The new theme id is
    persisted before any write, so a retry reuses it instead of duplicating again.
    """
    source_id = config["theme_id"]
    new_id = (step.result_json or {}).get("theme_id")
    if not new_id:  # first run — duplicate into a fresh draft and validate it
        dup = shopify.duplicate_theme(ctx, source_id, config["theme_name"])
        new_id = (dup or {}).get("id")
        if not new_id or new_id == source_id or not _draft_only((dup or {}).get("role")):
            raise ManagerError(
                "shopify_theme_not_draft",
                "Refused to build: the duplicated theme is not a new private draft.",
                502,
            )
        step.result_json = {"theme_id": new_id}  # persist the external id before any write
        session.commit()

    def guarded_batch(batch: list[dict]) -> list[str]:
        # Re-validate the live role before every write; refuse anything not a draft.
        if not _draft_only(shopify.get_theme_role(ctx, new_id)):
            raise ManagerError(
                "shopify_theme_not_draft",
                "Refused to write: the theme is no longer a private draft.",
                502,
            )
        return shopify.upsert_theme_file_batch(ctx, new_id, batch)

    rejected = upsert_theme_files(_theme_files(config), guarded_batch)
    admin_url, preview_url = shopify.theme_urls(ctx, new_id)
    errors = [f"theme file rejected: {rejected_key}" for rejected_key in rejected]
    return {"theme_id": new_id, "admin_url": admin_url, "preview_url": preview_url}, errors
