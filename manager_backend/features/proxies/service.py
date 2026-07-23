from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update as sql_update
from sqlalchemy.exc import IntegrityError, OperationalError
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


def _assigned_counts(session: Session, proxy_ids: list[str]) -> dict[str, int]:
    if not proxy_ids:
        return {}
    return {
        proxy_id: int(count)
        for proxy_id, count in session.execute(
            select(Profile.proxy_id, func.count(Profile.id))
            .where(Profile.proxy_id.in_(proxy_ids))
            .group_by(Profile.proxy_id)
        )
        if proxy_id is not None
    }


def proxy_to_dict(
    session: Session,
    proxy: Proxy,
    store: CredentialStore | None = None,
    *,
    assigned_count: int | None = None,
) -> dict:
    endpoint = "direct" if proxy.scheme == "direct" else f"{proxy.scheme}://{proxy.host}:{proxy.port}"
    username = None
    if store is not None and proxy.credential_ref:
        credential = store.get(proxy.credential_ref)
        username = credential.username if credential is not None else None
    return {
        "id": proxy.id,
        "label": proxy.label,
        "scheme": proxy.scheme,
        "host": proxy.host or "",
        "port": proxy.port,
        "username": username,
        "has_password": proxy.credential_ref is not None,
        "masked_endpoint": endpoint,
        "test_before_launch": proxy.test_before_launch,
        "assigned_profile_count": (
            _assigned_count(session, proxy.id) if assigned_count is None else assigned_count
        ),
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


def list_proxies(session: Session, store: CredentialStore | None = None) -> list[dict]:
    proxies = list(
        session.scalars(
            select(Proxy).where(Proxy.deleted_at.is_(None)).order_by(Proxy.label, Proxy.id)
        )
    )
    counts = _assigned_counts(session, [proxy.id for proxy in proxies])
    return [
        proxy_to_dict(session, proxy, store, assigned_count=counts.get(proxy.id, 0))
        for proxy in proxies
    ]


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
    committed = False
    try:
        session.commit()
        committed = True
    except IntegrityError:
        session.rollback()
        raise ManagerError("proxy_label_conflict", "A proxy with this label already exists.", 409) from None
    finally:
        # Compensate on ANY failure (IntegrityError or otherwise), not just one kind,
        # so a stored secret is never orphaned by an uncommitted row.
        if not committed and reference is not None:
            store.delete(reference)
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
    # Endpoint or credential edits invalidate a successful launch-check cache.
    proxy.exit_ip = None
    proxy.country = None
    proxy.city = None
    proxy.timezone = None
    proxy.asn = None
    proxy.organization = None
    proxy.latency_ms = None
    proxy.last_checked_at = None
    committed = False
    try:
        session.commit()
        committed = True
    except IntegrityError:
        session.rollback()
        raise ManagerError("proxy_label_conflict", "A proxy with this label already exists.", 409) from None
    finally:
        # Compensate on ANY failure: clean the NEW secret so it isn't orphaned. The
        # OLD secret is retained here and only deleted once the new ref is committed.
        if not committed and new_reference is not None:
            store.delete(new_reference)
    if old_reference is not None and old_reference != proxy.credential_ref:
        store.delete(old_reference)
    session.refresh(proxy)
    return proxy


def delete_proxy(session: Session, store: CredentialStore, proxy_id: str) -> None:
    try:
        guard = session.execute(
            sql_update(Proxy)
            .where(Proxy.id == proxy_id, Proxy.deleted_at.is_(None))
            .values(updated_at=Proxy.updated_at)
            .execution_options(synchronize_session=False)
        )
    except OperationalError:
        session.rollback()
        if _assigned_count(session, proxy_id):
            raise ManagerError(
                "proxy_in_use",
                "This proxy is assigned to one or more profiles.",
                409,
            ) from None
        raise ManagerError(
            "proxy_conflict",
            "The proxy changed while it was being deleted.",
            409,
        ) from None
    if guard.rowcount != 1:
        session.rollback()
        raise _not_found()

    proxy = get_proxy(session, proxy_id)
    count = _assigned_count(session, proxy.id)
    if count:
        session.rollback()
        raise ManagerError("proxy_in_use", "This proxy is assigned to one or more profiles.", 409)
    reference = proxy.credential_ref
    proxy.deleted_at = datetime.now(timezone.utc)
    proxy.credential_ref = None
    session.commit()
    if reference is not None:
        store.delete(reference)


def build_proxy_url(
    scheme: str,
    host: str,
    port: int | None,
    username: str | None = None,
    password: str | None = None,
) -> str | None:
    """Assemble a connection URL. Returns None for direct (no-proxy) mode.

    Kept transient by callers: never persisted or logged when it carries creds.
    """
    if scheme == "direct":
        return None
    authority = f"{host}:{port}"
    if username:
        from urllib.parse import quote

        authority = f"{quote(username, safe='')}:{quote(password or '', safe='')}@{authority}"
    return f"{scheme}://{authority}"


def resolve_proxy_url(session: Session, store: CredentialStore, proxy_id: str) -> str | None:
    proxy = get_proxy(session, proxy_id)
    credential = store.get(proxy.credential_ref) if proxy.credential_ref else None
    username = credential.username if credential is not None else None
    password = credential.password if credential is not None else None
    return build_proxy_url(proxy.scheme, proxy.host, proxy.port, username, password)


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


# Country -> BCP-47 locale for profiles that derive their locale from the proxy.
# Coarse (one language per country) but enough to keep navigator.language aligned
# with the exit IP; anything unmapped falls back to en-US.
_LOCALE_BY_COUNTRY = {
    "US": "en-US", "GB": "en-GB", "CA": "en-CA", "AU": "en-AU", "IE": "en-IE",
    "NZ": "en-NZ", "SG": "en-SG", "IN": "en-IN", "DE": "de-DE", "AT": "de-AT",
    "FR": "fr-FR", "ES": "es-ES", "MX": "es-MX", "IT": "it-IT", "NL": "nl-NL",
    "BE": "nl-BE", "PT": "pt-PT", "BR": "pt-BR", "JP": "ja-JP", "KR": "ko-KR",
    "VN": "vi-VN", "TH": "th-TH", "RU": "ru-RU", "UA": "uk-UA", "PL": "pl-PL",
    "TR": "tr-TR", "SE": "sv-SE", "NO": "nb-NO", "DK": "da-DK", "FI": "fi-FI",
}


def _apply_proxy_geo(snapshot: dict, result) -> None:
    """When a profile derives geo from its proxy, stamp the freshly measured
    exit-IP timezone (and a matching locale) onto the launch snapshot so the
    browser clock/language agree with the IP. Without this, geo_mode="proxy" is
    a no-op and the browser reports the host timezone -> detection sites flag a
    timezone/IP mismatch ("timezone spoofed")."""
    location = snapshot.get("location") or {}
    if location.get("geo_mode") != "proxy":
        return
    if getattr(result, "timezone", None):
        snapshot["timezone"] = result.timezone
    if not snapshot.get("locale") and getattr(result, "country", None):
        snapshot["locale"] = _LOCALE_BY_COUNTRY.get(result.country, "en-US")


_PREFLIGHT_CACHE_MAX_AGE = timedelta(seconds=60)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _cached_quick_test(proxy: Proxy, *, now: datetime) -> QuickTestResult | None:
    checked_at = proxy.last_checked_at
    if (
        checked_at is None
        or not proxy.exit_ip
        or _as_utc(now) - _as_utc(checked_at) > _PREFLIGHT_CACHE_MAX_AGE
    ):
        return None
    return QuickTestResult(
        exit_ip=proxy.exit_ip,
        exit_ip_matches=True,
        latency_ms=proxy.latency_ms or 0,
        checked_at=_as_utc(checked_at),
        country=proxy.country,
        city=proxy.city,
        timezone=proxy.timezone,
        asn=proxy.asn,
        organization=proxy.organization,
    )


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
            if (
                not snapshot.get("test_proxy_before_launch", True)
                or not proxy.test_before_launch
            ):
                return proxy_url
            result = _cached_quick_test(proxy, now=datetime.now(timezone.utc))
            used_cached_result = result is not None
            try:
                if result is None:
                    result = tester.run_fast(proxy_url, timeout_seconds=5)
            except ProxyTestFailure:
                raise ManagerError(
                    "proxy_preflight_failed",
                    "The assigned proxy is unavailable.",
                    409,
                ) from None
            if not used_cached_result:
                cache_quick_test(session, proxy, result)
            _apply_proxy_geo(snapshot, result)
            snapshot["proxy_exit_ip"] = result.exit_ip
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
