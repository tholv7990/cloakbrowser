from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import Profile, Proxy, ProxyQualityRun
from .credentials import CredentialStore, ProxyCredential
from .schemas import ProxyWrite
from .testing import QuickTestResult
from .testing import ProxyTestFailure


def _not_found() -> ManagerError:
    return ManagerError("proxy_not_found", "The requested proxy was not found.", 404)


def get_proxy(session: Session, proxy_id: str) -> Proxy:
    proxy = session.get(Proxy, proxy_id)
    if proxy is None or proxy.deleted_at is not None:
        raise _not_found()
    return proxy


def _assigned_count(session: Session, proxy_id: str) -> int:
    return int(session.scalar(select(func.count(Profile.id)).where(Profile.proxy_id == proxy_id)) or 0)


def proxy_to_dict(session: Session, proxy: Proxy) -> dict:
    endpoint = "direct" if proxy.scheme == "direct" else f"{proxy.scheme}://{proxy.host}:{proxy.port}"
    return {
        "id": proxy.id,
        "label": proxy.label,
        "scheme": proxy.scheme,
        "host": proxy.host or "",
        "port": proxy.port,
        "username": None,
        "has_password": proxy.credential_ref is not None,
        "masked_endpoint": endpoint,
        "test_before_launch": proxy.test_before_launch,
        "assigned_profile_count": _assigned_count(session, proxy.id),
        "exit_ip": proxy.exit_ip,
        "country": proxy.country,
        "city": proxy.city,
        "timezone": proxy.timezone,
        "asn": proxy.asn,
        "organization": proxy.organization,
        "proxy_type": proxy.proxy_type,
        "type_confidence": proxy.type_confidence,
        "reputation": proxy.reputation,
        "latency_ms": proxy.latency_ms,
        "last_checked_at": proxy.last_checked_at,
        "created_at": proxy.created_at,
        "updated_at": proxy.updated_at,
    }


def list_proxies(session: Session) -> list[dict]:
    proxies = list(
        session.scalars(
            select(Proxy).where(Proxy.deleted_at.is_(None)).order_by(Proxy.label, Proxy.id)
        )
    )
    return [proxy_to_dict(session, proxy) for proxy in proxies]


def create_proxy(session: Session, store: CredentialStore, payload: ProxyWrite) -> Proxy:
    reference = None
    if payload.username is not None:
        reference = str(uuid4())
        store.put(reference, ProxyCredential(payload.username, payload.password or ""))
    proxy = Proxy(
        label=payload.label,
        scheme=payload.scheme,
        host=payload.host or None,
        port=payload.port,
        credential_ref=reference,
        test_before_launch=payload.test_before_launch,
    )
    session.add(proxy)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if reference is not None:
            store.delete(reference)
        raise ManagerError("proxy_label_conflict", "A proxy with this label already exists.", 409) from None
    session.refresh(proxy)
    return proxy


def update_proxy(
    session: Session, store: CredentialStore, proxy_id: str, payload: ProxyWrite
) -> Proxy:
    proxy = get_proxy(session, proxy_id)
    old_reference = proxy.credential_ref
    new_reference = None
    if payload.username is not None:
        new_reference = str(uuid4())
        store.put(new_reference, ProxyCredential(payload.username, payload.password or ""))
        proxy.credential_ref = new_reference
    elif payload.clear_credentials or payload.scheme == "direct":
        proxy.credential_ref = None
    proxy.label = payload.label
    proxy.scheme = payload.scheme
    proxy.host = payload.host or None
    proxy.port = payload.port
    proxy.test_before_launch = payload.test_before_launch
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if new_reference is not None:
            store.delete(new_reference)
        raise ManagerError("proxy_label_conflict", "A proxy with this label already exists.", 409) from None
    if old_reference is not None and old_reference != proxy.credential_ref:
        store.delete(old_reference)
    session.refresh(proxy)
    return proxy


def delete_proxy(session: Session, store: CredentialStore, proxy_id: str) -> None:
    proxy = get_proxy(session, proxy_id)
    count = _assigned_count(session, proxy.id)
    if count:
        raise ManagerError("proxy_in_use", "This proxy is assigned to one or more profiles.", 409)
    reference = proxy.credential_ref
    proxy.deleted_at = datetime.now(timezone.utc)
    proxy.credential_ref = None
    session.commit()
    if reference is not None:
        store.delete(reference)


def resolve_proxy_url(session: Session, store: CredentialStore, proxy_id: str) -> str | None:
    proxy = get_proxy(session, proxy_id)
    if proxy.scheme == "direct":
        return None
    credential = store.get(proxy.credential_ref) if proxy.credential_ref else None
    authority = f"{proxy.host}:{proxy.port}"
    if credential is not None:
        from urllib.parse import quote

        authority = f"{quote(credential.username, safe='')}:{quote(credential.password, safe='')}@{authority}"
    return f"{proxy.scheme}://{authority}"


def cache_quick_test(session: Session, proxy: Proxy, result: QuickTestResult) -> None:
    proxy.exit_ip = result.exit_ip
    proxy.country = result.country
    proxy.city = result.city
    proxy.timezone = result.timezone
    proxy.asn = result.asn
    proxy.organization = result.organization
    proxy.latency_ms = result.latency_ms
    proxy.last_checked_at = result.checked_at
    session.commit()


def build_proxy_preflight(session_factory, store: CredentialStore, tester):
    def preflight(snapshot: dict) -> str | None:
        proxy_id = snapshot.get("proxy_id")
        if not proxy_id:
            return None
        with session_factory() as session:
            proxy = get_proxy(session, proxy_id)
            proxy_url = resolve_proxy_url(session, store, proxy_id)
            if proxy_url is None:
                return None
            try:
                result = tester.run(proxy_url, timeout_seconds=20)
            except ProxyTestFailure:
                raise ManagerError(
                    "proxy_preflight_failed",
                    "The assigned proxy is unavailable.",
                    409,
                ) from None
            cache_quick_test(session, proxy, result)
            return proxy_url

    return preflight


def create_quality_run(session: Session, proxy_id: str) -> ProxyQualityRun:
    get_proxy(session, proxy_id)
    active = session.scalar(
        select(ProxyQualityRun).where(
            ProxyQualityRun.proxy_id == proxy_id,
            ProxyQualityRun.state.in_({"queued", "running"}),
        )
    )
    if active is not None:
        raise ManagerError(
            "proxy_quality_already_running", "A quality test is already active.", 409
        )
    run = ProxyQualityRun(proxy_id=proxy_id, state="queued", last_message="queued")
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ManagerError(
            "proxy_quality_already_running", "A quality test is already active.", 409
        ) from None
    session.refresh(run)
    return run


def quality_report_to_dict(run: ProxyQualityRun) -> dict:
    if run.report is not None:
        return run.report
    finding = {"status": "unknown", "detail": "No observation was available."}
    return {
        "id": run.id,
        "proxy_id": run.proxy_id,
        "state": "failed" if run.state == "cancelled" else run.state,
        "proxy_type": None,
        "type_confidence": None,
        "reputation": None,
        "matched_lists": [],
        "google_outcome": None,
        "turnstile_outcome": None,
        "alignment": {name: finding for name in ("http", "webrtc", "dns", "timezone", "locale")},
        "latency_ms": None,
        "exit_ip": None,
        "country": None,
        "city": None,
        "timezone": None,
        "asn": None,
        "organization": None,
        "screenshot_path": None,
        "report_path": None,
        "observed_scope": "Timestamped observation; not a permanent cleanliness guarantee.",
        "checked_at": run.checked_at or run.created_at,
    }
