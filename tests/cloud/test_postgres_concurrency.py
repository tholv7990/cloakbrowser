"""Real-concurrency tests for the two race-safe paths — run against PostgreSQL.

SQLite serializes writers and ignores ``FOR UPDATE``, so it can't prove the row-lock
logic actually holds under parallel connections. These tests spin many threads (each
its own session/connection) at a shared barrier and assert the invariants:

  * activation-key redemption never oversells ``uses_remaining`` across devices;
  * a same-device redemption race consumes exactly one use;
  * two simultaneous presentations of one refresh token => exactly one rotates and
    the other is caught as reuse (which durably revokes the family).

Skipped unless ``CLOUD_TEST_DATABASE_URL`` points at a reachable Postgres (CI sets it;
locally: ``docker run -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres`` then
``CLOUD_TEST_DATABASE_URL=postgresql+psycopg2://postgres:pg@127.0.0.1:5432/postgres``).
"""

from __future__ import annotations

import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from cloud import models
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.entitlements import generate_signing_keypair
from cloud.features.auth.service import AuthError, create_session, rotate_refresh
from cloud.keys import generate_activation_key, key_verifier
from cloud.licensing import RedeemError, redeem_key

PG_URL = os.environ.get("CLOUD_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL or not PG_URL.startswith("postgresql"),
    reason="set CLOUD_TEST_DATABASE_URL to a PostgreSQL DSN to run the concurrency suite",
)

PEPPER = b"pg-concurrency-pepper"
PRIVATE_KEY, _PUBLIC_KEY = generate_signing_keypair()
SETTINGS = generate_test_settings()


@pytest.fixture
def factory():
    engine = create_engine_for(PG_URL)
    try:
        with engine.connect() as _c:  # fail fast -> skip if the DSN isn't reachable
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable: {exc}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield create_session_factory(engine)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _run_at_barrier(n, worker):
    """Fire ``n`` copies of ``worker(i)`` as simultaneously as threads allow."""
    barrier = threading.Barrier(n)

    def task(i):
        barrier.wait()
        return worker(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(task, range(n)))


def _seed_account(factory, *, devices=1):
    with factory() as s:
        s.add(models.Plan(id="pro", name="Pro", features={"media": True}))
        user = models.User(email="u@example.com", password_hash="h", status="active")
        s.add(user)
        s.flush()
        device_ids = []
        for i in range(devices):
            d = models.Device(user_id=user.id, public_key=f"pk-{i}")
            s.add(d)
            s.flush()
            device_ids.append(d.id)
        s.commit()
        return user.id, device_ids


def _seed_key(factory, *, max_uses):
    display, parts = generate_activation_key()
    with factory() as s:
        key = models.ActivationKey(
            verifier=key_verifier(display, PEPPER),
            lookup_prefix=parts["lookup_prefix"],
            last4=parts["last4"],
            plan_id="pro",
            max_uses=max_uses,
            uses_remaining=max_uses,
        )
        s.add(key)
        s.commit()
        return display, key.id


def _redeem(factory, *, raw_key, user_id, device_id):
    with factory() as s:
        try:
            redeem_key(
                s,
                raw_key=raw_key,
                user_id=user_id,
                device_id=device_id,
                pepper=PEPPER,
                private_key=PRIVATE_KEY,
            )
            s.commit()
            return "ok"
        except RedeemError as exc:
            s.rollback()
            return exc.code


def test_no_oversell_under_concurrent_redemption(factory):
    # 8 devices race to redeem a key that only has 3 uses.
    user_id, device_ids = _seed_account(factory, devices=8)
    raw_key, key_id = _seed_key(factory, max_uses=3)

    outcomes = Counter(
        _run_at_barrier(
            8,
            lambda i: _redeem(
                factory, raw_key=raw_key, user_id=user_id, device_id=device_ids[i]
            ),
        )
    )

    assert outcomes["ok"] == 3, outcomes
    assert outcomes["key_exhausted"] == 5, outcomes
    with factory() as s:
        key = s.get(models.ActivationKey, key_id)
        assert key.uses_remaining == 0  # never went negative, never oversold
        redemptions = s.scalars(
            select(models.Redemption).where(models.Redemption.key_id == key_id)
        ).all()
        assert len(redemptions) == 3


def test_same_device_concurrent_redeem_consumes_one_use(factory):
    # The same device redeems the same key 6 times at once: idempotent, one use spent.
    user_id, device_ids = _seed_account(factory, devices=1)
    raw_key, key_id = _seed_key(factory, max_uses=5)

    outcomes = Counter(
        _run_at_barrier(
            6,
            lambda _i: _redeem(
                factory, raw_key=raw_key, user_id=user_id, device_id=device_ids[0]
            ),
        )
    )

    # Every attempt succeeds (first consumes a use, the rest re-issue idempotently),
    # or loses the insert race and reports the redeem_conflict backstop — never a use
    # miscount.
    assert outcomes["ok"] + outcomes["redeem_conflict"] == 6, outcomes
    with factory() as s:
        key = s.get(models.ActivationKey, key_id)
        assert key.uses_remaining == 4  # exactly ONE use consumed for the device
        redemptions = s.scalars(
            select(models.Redemption).where(models.Redemption.device_id == device_ids[0])
        ).all()
        assert len(redemptions) == 1  # unique(key_id, device_id) held


def test_concurrent_refresh_reuse_is_detected(factory):
    user_id, device_ids = _seed_account(factory, devices=1)
    with factory() as s:
        user = s.get(models.User, user_id)
        device = s.get(models.Device, device_ids[0])
        issued = create_session(s, user=user, device=device, settings=SETTINGS)
        s.commit()
        raw_refresh = issued.refresh_token
        family_id = issued.session.family_id

    def worker(_i):
        with factory() as s:
            try:
                rotate_refresh(s, raw_refresh=raw_refresh, settings=SETTINGS)
                s.commit()
                return "rotated"
            except AuthError as exc:
                # rotate_refresh already committed the reuse-revoke on its own session.
                return exc.code

    outcomes = Counter(_run_at_barrier(2, worker))

    # FOR UPDATE serializes the pair: exactly one wins, the other is reuse.
    assert outcomes["rotated"] == 1, outcomes
    assert outcomes["refresh_reuse"] == 1, outcomes
    # Containment persisted: the whole family is revoked (the winner's fresh child too).
    with factory() as s:
        rows = s.scalars(
            select(models.Session).where(models.Session.family_id == family_id)
        ).all()
        assert rows and all(r.revoked_at is not None for r in rows)
        assert all(r.reuse_detected_at is not None for r in rows)
