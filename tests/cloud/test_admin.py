from __future__ import annotations

import pytest
from sqlalchemy import select

from cloud import models
from cloud.admin import issue_key, lookup_key, set_key_status, set_user_status
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.entitlements import verify_entitlement
from cloud.features.auth import service as auth
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


def test_suspend_user_bans_and_kicks_sessions(session_factory):
    ids = _seed(session_factory)
    with session_factory() as session:  # give the user a live session first
        user = session.get(models.User, ids["user"])
        device = session.get(models.Device, ids["device"])
        auth.create_session(session, user=user, device=device, settings=SETTINGS)
        session.commit()

    with session_factory() as session:
        assert set_user_status(session, email="u@example.com", status="suspended") is True
        session.commit()

    with session_factory() as session:
        assert session.get(models.User, ids["user"]).status == "suspended"
        # every live session is revoked -> the device is kicked
        rows = session.scalars(
            select(models.Session).where(models.Session.user_id == ids["user"])
        ).all()
        assert rows and all(r.revoked_at is not None for r in rows)
        events = session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.action == "user.suspended")
        ).all()
        assert len(events) == 1 and events[0].subject_id == ids["user"]


def test_restore_user_reactivates(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        assert set_user_status(session, email="u@example.com", status="suspended") is True
        assert set_user_status(session, email="u@example.com", status="active") is True
        session.commit()
    with session_factory() as session:
        user = session.scalars(
            select(models.User).where(models.User.email == "u@example.com")
        ).one()
        assert user.status == "active"


def test_suspend_unknown_user_returns_false(session_factory):
    with session_factory() as session:
        assert set_user_status(session, email="nobody@example.com", status="suspended") is False


def test_set_user_status_rejects_bad_status(session_factory):
    _seed(session_factory)
    with session_factory() as session:
        with pytest.raises(ValueError):
            set_user_status(session, email="u@example.com", status="revoked")
