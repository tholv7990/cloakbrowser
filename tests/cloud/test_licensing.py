from __future__ import annotations

from datetime import timedelta

import pytest

from cloud import models
from cloud.db import create_engine_for, create_session_factory, utc_now
from cloud.db import Base
from cloud.entitlements import generate_signing_keypair, verify_entitlement
from cloud.keys import generate_activation_key, key_verifier
from cloud.licensing import RedeemError, redeem_key

PEPPER = b"test-pepper"
PRIVATE_KEY, PUBLIC_KEY = generate_signing_keypair()


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _setup(session_factory, *, max_uses=1, status="active", expires_at=None):
    with session_factory() as session:
        session.add(
            models.Plan(
                id="pro",
                name="Pro",
                max_devices=3,
                max_profiles=100,
                max_sessions=10,
                features={"media": True, "automation": False},
            )
        )
        user = models.User(email="u@example.com", password_hash="h")
        session.add(user)
        session.flush()
        device_a = models.Device(user_id=user.id, public_key="pk-a")
        device_b = models.Device(user_id=user.id, public_key="pk-b")
        session.add_all([device_a, device_b])
        session.flush()
        display, parts = generate_activation_key()
        key = models.ActivationKey(
            verifier=key_verifier(display, PEPPER),
            lookup_prefix=parts["lookup_prefix"],
            last4=parts["last4"],
            plan_id="pro",
            max_uses=max_uses,
            uses_remaining=max_uses,
            status=status,
            expires_at=expires_at,
        )
        session.add(key)
        session.commit()
        return {
            "display": display,
            "user_id": user.id,
            "device_a": device_a.id,
            "device_b": device_b.id,
            "key_id": key.id,
        }


def _redeem(session_factory, ctx, device_id):
    with session_factory() as session:
        result = redeem_key(
            session,
            raw_key=ctx["display"],
            user_id=ctx["user_id"],
            device_id=device_id,
            pepper=PEPPER,
            private_key=PRIVATE_KEY,
        )
        session.commit()
        return result


def _uses_remaining(session_factory, key_id):
    with session_factory() as session:
        return session.get(models.ActivationKey, key_id).uses_remaining


def test_redeem_issues_a_verifiable_entitlement_and_consumes_one_use(session_factory):
    ctx = _setup(session_factory, max_uses=1)
    result = _redeem(session_factory, ctx, ctx["device_a"])

    assert result.reused is False
    claims = verify_entitlement(result.token, PUBLIC_KEY)
    assert claims["sub"] == ctx["user_id"]
    assert claims["device_id"] == ctx["device_a"]
    assert claims["plan"] == "pro"
    assert claims["features"] == ["media"]  # only enabled features
    assert claims["profile_limit"] == 100
    assert claims["session_limit"] == 10
    assert claims["exp"] > claims["iat"]
    assert claims["offline_grace_deadline"] > claims["exp"]
    assert _uses_remaining(session_factory, ctx["key_id"]) == 0


def test_second_redeem_same_device_is_idempotent(session_factory):
    ctx = _setup(session_factory, max_uses=1)
    _redeem(session_factory, ctx, ctx["device_a"])
    again = _redeem(session_factory, ctx, ctx["device_a"])  # retry, same device

    assert again.reused is True
    assert verify_entitlement(again.token, PUBLIC_KEY)["device_id"] == ctx["device_a"]
    # No further use consumed by the idempotent retry.
    assert _uses_remaining(session_factory, ctx["key_id"]) == 0


def test_single_use_key_is_exhausted_on_a_second_device(session_factory):
    ctx = _setup(session_factory, max_uses=1)
    _redeem(session_factory, ctx, ctx["device_a"])
    with pytest.raises(RedeemError) as error:
        _redeem(session_factory, ctx, ctx["device_b"])
    assert error.value.code == "key_exhausted"


def test_multi_use_key_covers_several_devices_then_exhausts(session_factory):
    ctx = _setup(session_factory, max_uses=2)
    assert _redeem(session_factory, ctx, ctx["device_a"]).reused is False
    assert _redeem(session_factory, ctx, ctx["device_b"]).reused is False
    assert _uses_remaining(session_factory, ctx["key_id"]) == 0
    # A third distinct device is over the cap.
    with session_factory() as session:
        third = models.Device(user_id=ctx["user_id"], public_key="pk-c")
        session.add(third)
        session.commit()
        third_id = third.id
    with pytest.raises(RedeemError) as error:
        _redeem(session_factory, ctx, third_id)
    assert error.value.code == "key_exhausted"


def test_invalid_key_is_rejected(session_factory):
    ctx = _setup(session_factory)
    with session_factory() as session:
        with pytest.raises(RedeemError) as error:
            redeem_key(
                session,
                raw_key="PLASMA-0000-0000-0000-0000-0000-0000",
                user_id=ctx["user_id"],
                device_id=ctx["device_a"],
                pepper=PEPPER,
                private_key=PRIVATE_KEY,
            )
    assert error.value.code == "invalid_key"


@pytest.mark.parametrize(
    "status,expired,expected",
    [
        ("suspended", False, "key_suspended"),
        ("revoked", False, "key_revoked"),
        ("active", True, "key_expired"),
    ],
)
def test_bad_key_states_are_rejected(session_factory, status, expired, expected):
    expires_at = utc_now() - timedelta(days=1) if expired else None
    ctx = _setup(session_factory, status=status, expires_at=expires_at)
    with pytest.raises(RedeemError) as error:
        _redeem(session_factory, ctx, ctx["device_a"])
    assert error.value.code == expected
