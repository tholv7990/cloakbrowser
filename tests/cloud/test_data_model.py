from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from cloud import models
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.keys import (
    generate_activation_key,
    key_verifier,
    normalize_email,
    normalize_key,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _seed_plan(session) -> models.Plan:
    plan = models.Plan(
        id="pro",
        name="Pro",
        max_devices=3,
        max_profiles=100,
        max_sessions=10,
        features={"media": True, "automation": True},
    )
    session.add(plan)
    session.commit()
    return plan


def test_schema_builds_and_is_queryable(session_factory):
    # create_all already ran in the fixture; every core table is present + empty.
    with session_factory() as session:
        for model in (
            models.User,
            models.Device,
            models.Session,
            models.Plan,
            models.ActivationKey,
            models.Redemption,
            models.Entitlement,
            models.AuditEvent,
            models.UpdateRelease,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_transient_state_tables_build(session_factory):
    with session_factory() as session:
        for model in (
            models.OAuthAuthorizationCode,
            models.IdempotencyKey,
            models.AuthThrottle,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_email_normalization_is_unicode_casefolded():
    # casefold() (not lower()) collapses ß -> ss, so visually distinct addresses
    # that are the same identity can't become two rows.
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"
    assert normalize_email("Straße@x.com") == normalize_email("STRASSE@x.com")


def test_role_check_rejects_unknown_role(session_factory):
    with session_factory() as session:
        session.add(
            models.User(email="r@example.com", password_hash="h", role="superadmin")
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_email_is_unique_case_insensitively(session_factory):
    with session_factory() as session:
        session.add(
            models.User(email=normalize_email("  Owner@Example.COM "), password_hash="argon2$a")
        )
        session.commit()
    with session_factory() as session:
        session.add(models.User(email=normalize_email("owner@example.com"), password_hash="argon2$b"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_key_verifier_is_typo_tolerant_and_pepper_bound():
    display, _parts = generate_activation_key()
    pepper = b"server-pepper"
    # Case, spaces, and dash noise all normalize to the same verifier.
    noisy = f"  {display.lower().replace('-', ' - ')}  "
    assert key_verifier(display, pepper) == key_verifier(noisy, pepper)
    # A different pepper yields a different verifier (DB leak alone is useless).
    assert key_verifier(display, pepper) != key_verifier(display, b"other-pepper")
    # Crockford lenient letter mapping (O->0, I/L->1, U->V).
    assert normalize_key("plasma-oil0") == "0110"


def test_activation_key_row_never_stores_the_raw_key(session_factory):
    display, parts = generate_activation_key()
    pepper = b"server-pepper"
    with session_factory() as session:
        _seed_plan(session)
        session.add(
            models.ActivationKey(
                verifier=key_verifier(display, pepper),
                lookup_prefix=parts["lookup_prefix"],
                last4=parts["last4"],
                plan_id="pro",
                max_uses=1,
                uses_remaining=1,
            )
        )
        session.commit()
        row = session.scalars(select(models.ActivationKey)).one()

    body = normalize_key(display)  # 24 symbols
    middle = body[4:20]  # the 16 symbols not exposed as prefix/last4
    stored_blob = f"{row.verifier}{row.lookup_prefix}{row.last4}"
    assert middle not in stored_blob  # the key is unrecoverable from the row
    assert row.verifier != body  # verifier is the HMAC, not the key


def test_one_time_key_cannot_be_double_redeemed(session_factory):
    # The unique(key_id, device_id) constraint is the race-safety guarantee: two
    # redeems of the same key on the same device cannot both commit.
    with session_factory() as session:
        _seed_plan(session)
        user = models.User(email="u@example.com", password_hash="h")
        session.add(user)
        session.flush()
        device = models.Device(user_id=user.id, public_key="ed25519-pub")
        key = models.ActivationKey(
            verifier="v", lookup_prefix="PLASMA-AAAA", last4="ZZZZ", plan_id="pro"
        )
        session.add_all([device, key])
        session.commit()
        ids = (key.id, user.id, device.id)

    with session_factory() as session:
        session.add(models.Redemption(key_id=ids[0], user_id=ids[1], device_id=ids[2]))
        session.commit()  # first redeem wins

    with session_factory() as session:
        session.add(models.Redemption(key_id=ids[0], user_id=ids[1], device_id=ids[2]))
        with pytest.raises(IntegrityError):
            session.commit()  # second redeem blocked by the unique constraint


def test_active_device_count_for_limit_enforcement(session_factory):
    from cloud.db import utc_now

    with session_factory() as session:
        user = models.User(email="d@example.com", password_hash="h")
        session.add(user)
        session.flush()
        session.add_all(
            [
                models.Device(user_id=user.id, public_key="k1"),
                models.Device(user_id=user.id, public_key="k2"),
                models.Device(user_id=user.id, public_key="k3", revoked_at=utc_now()),
            ]
        )
        session.commit()
        active = session.scalar(
            select(func.count())
            .select_from(models.Device)
            .where(models.Device.user_id == user.id, models.Device.revoked_at.is_(None))
        )
        assert active == 2  # revoked device excluded from the plan's device limit
