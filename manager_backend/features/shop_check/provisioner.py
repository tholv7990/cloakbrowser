"""Shop-check provisioning: worker allocation, per-profile 711 proxy, profile
creation, and durable ownership.

No threads and no browser-page automation here — the coordinator drives these
functions on its worker threads. Everything is idempotent so a restart never
creates a duplicate worker, proxy, or profile.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...features.profiles.service import create_owned_profile
from ...features.profiles.schemas import ProfileCreate
from ...features.proxies.credentials import CredentialStore
from ...features.proxies.providers import generate_and_store
from ...features.proxies.service import cache_quick_test, resolve_proxy_url
from ...features.proxies.testing import ProxyTestFailure
from ...models import Proxy, ShopCheckEmail, ShopCheckWorker, new_id
from .service import recompute_run, require_run


class ProxyProvisionError(Exception):
    """A proxy could not be provisioned. `category` is one of: credential_missing,
    provider_unavailable, generation_failed, preflight_failed, timeout, cancelled."""

    def __init__(self, category: str, message: str = ""):
        self.category = category
        super().__init__(message or category)


def group_workers(session: Session, run_id: str) -> int:
    """Divide the run's emails (in input/ordinal order) into groups of at most
    emails_per_profile and create exactly one worker per group. Idempotent: a
    worker ordinal already present is reused, and an email already assigned keeps
    its worker. Returns the number of worker groups.
    """
    run = require_run(session, run_id)
    per = run.emails_per_profile
    emails = list(
        session.scalars(
            select(ShopCheckEmail)
            .where(ShopCheckEmail.run_id == run_id)
            .order_by(ShopCheckEmail.ordinal, ShopCheckEmail.id)
        )
    )
    existing = {
        worker.ordinal: worker
        for worker in session.scalars(
            select(ShopCheckWorker).where(ShopCheckWorker.run_id == run_id)
        )
    }
    group_count = math.ceil(len(emails) / per) if emails else 0
    for ordinal in range(group_count):
        group = emails[ordinal * per : (ordinal + 1) * per]
        worker = existing.get(ordinal)
        if worker is None:
            worker = ShopCheckWorker(
                run_id=run_id,
                ordinal=ordinal,
                state="pending",
                assigned_count=len(group),
            )
            session.add(worker)
            session.flush()
            existing[ordinal] = worker
        for email in group:
            if email.worker_id is None:
                email.worker_id = worker.id
    session.commit()
    # worker_count is recomputed from committed worker rows, never guessed.
    recompute_run(session, run_id)
    return group_count


def provision_proxy(
    session_factory,
    store: CredentialStore,
    provider_client,
    tester,
    *,
    region: str | None,
    is_cancelled: Callable[[], bool] = lambda: False,
    max_attempts: int = 3,
) -> str:
    """Generate one sticky 711 residential proxy for a temporary profile and
    preflight it before use. A missing credential or a down provider fails fast;
    an unhealthy proxy is retried with a fresh session directive up to
    max_attempts. The generated proxy is a normal pool row (preserved on cleanup);
    its secret lives only in CredentialStore. Never logs an authenticated URL.
    """
    for attempt in range(1, max_attempts + 1):
        if is_cancelled():
            raise ProxyProvisionError("cancelled")

        # Generate on a fresh short-lived session — the network call happens
        # inside generate_and_store BEFORE its commit, so no write txn is held
        # open across the network.
        try:
            with session_factory() as session:
                result = generate_and_store(
                    session,
                    store,
                    provider_client,
                    provider="seveneleven",
                    count=1,
                    country=region or "",  # empty => provider-supported random region
                    session_type="sticky",  # one stable exit per profile (design §3/§13)
                )
            proxy_id = result["proxy_ids"][0]
        except ManagerError as error:
            if error.code == "proxy_provider_not_configured":
                raise ProxyProvisionError("credential_missing") from None
            raise ProxyProvisionError("generation_failed") from None
        except Exception:
            raise ProxyProvisionError("provider_unavailable") from None

        if is_cancelled():
            raise ProxyProvisionError("cancelled")

        # Preflight with no write transaction open.
        with session_factory() as session:
            url = resolve_proxy_url(session, store, proxy_id)
        try:
            outcome = tester.run_fast(url, timeout_seconds=3)
        except ProxyTestFailure as failure:
            category = "timeout" if failure.category == "timeout" else "preflight_failed"
            if attempt < max_attempts:
                continue  # regenerate a fresh route and retry
            raise ProxyProvisionError(category) from None

        # Healthy: cache exit metadata on the proxy row.
        with session_factory() as session:
            proxy = session.get(Proxy, proxy_id)
            if proxy is not None:
                cache_quick_test(session, proxy, outcome)
                session.commit()
        return proxy_id

    raise ProxyProvisionError("preflight_failed")


def provision_profile(
    session: Session,
    worker_id: str,
    *,
    proxy_id: str,
    target_url: str,
    name: str,
) -> str:
    """Create the temporary profile owned by this worker, recording ownership
    BEFORE the profile exists so provenance is durable across a crash. Idempotent:
    a worker that already owns a profile keeps it, and re-creating an existing id
    is a no-op. The immutability trigger blocks any later re-pointing.
    """
    worker = session.get(ShopCheckWorker, worker_id)
    if worker.profile_id is None:
        profile_id = new_id()
        # Ownership first: NULL -> value is allowed by the immutability trigger; a
        # crash after this leaves a resolvable (run_id, profile_id) record that the
        # idempotent create below (or recovery) completes.
        session.execute(
            update(ShopCheckWorker)
            .where(
                ShopCheckWorker.id == worker_id,
                ShopCheckWorker.profile_id.is_(None),
            )
            .values(profile_id=profile_id, proxy_id=proxy_id)
        )
        session.commit()
    profile_id = session.get(ShopCheckWorker, worker_id).profile_id
    create_owned_profile(
        session,
        profile_id,
        ProfileCreate(name=name, startup_urls=[target_url], proxy_id=proxy_id),
    )
    return profile_id
