from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud import models
from cloud.admin import issue_key, lookup_key, set_key_status
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.entitlements import verify_entitlement
from cloud.keys import normalize_key
from cloud.licensing import RedeemError, redeem_key

SETTINGS = generate_test_settings()


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _seed(session_factory):
    with session_factory() as session:
        session.add(
            models.Plan(id="pro", name="Pro", max_devices=3, max_profiles=100, max_sessions=10)
        )
        session.flush()
        user = models.User(email="u@example.com", password_hash="h", status="active")
        session.add(user)
        session.flush()
        device = models.Device(user_id=user.id, public_key="pk")
        session.add(device)
        session.commit()
        return {"user": user.id, "device": device.id}


def test_issued_key_is_redeemable_and_audited(session_factory):
    ids = _seed(session_factory)
    with session_factory() as session:
        display, key = issue_key(
            session, plan_id="pro", pepper=SETTINGS.activation_pepper, max_uses=1
        )
        session.commit()
        key_id = key.id

    with session_factory() as session:
        events = session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.action == "key.issue")
        ).all()
        assert len(events) == 1 and events[0].subject_id == key_id

    with session_factory() as session:
        result = redeem_key(
            session,
            raw_key=display,
            user_id=ids["user"],
            device_id=ids["device"],
            pepper=SETTINGS.activation_pepper,
            private_key=SETTINGS.signing_private_key,
        )
        session.commit()
        assert verify_entitlement(result.token, SETTINGS.signing_public_key)["plan"] == "pro"


def test_lookup_returns_safe_fields_and_never_the_key(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        display, key = issue_key(session, plan_id="pro", pepper=SETTINGS.activation_pepper)
        session.commit()
        prefix, key_id = key.lookup_prefix, key.id

    with session_factory() as session:
        rows = lookup_key(session, lookup_prefix=prefix)
    assert len(rows) == 1
    row = rows[0]
    assert row["key_id"] == key_id and row["plan"] == "pro" and row["status"] == "active"
    # The secret middle of the key never appears in a support lookup.
    middle = normalize_key(display)[4:20]
    assert middle not in str(row)


def test_revoke_blocks_redemption(session_factory):
    ids = _seed(session_factory)
    with session_factory() as session:
        display, key = issue_key(session, plan_id="pro", pepper=SETTINGS.activation_pepper)
        session.commit()
        key_id = key.id

    with session_factory() as session:
        assert set_key_status(session, key_id=key_id, status="revoked") is True
        session.commit()

    with session_factory() as session:
        with pytest.raises(RedeemError) as error:
            redeem_key(
                session,
                raw_key=display,
                user_id=ids["user"],
                device_id=ids["device"],
                pepper=SETTINGS.activation_pepper,
                private_key=SETTINGS.signing_private_key,
            )
    assert error.value.code == "key_revoked"


def test_issue_rejects_unknown_plan(session_factory):
    with session_factory() as session:
        with pytest.raises(ValueError):
            issue_key(session, plan_id="does-not-exist", pepper=SETTINGS.activation_pepper)
