from __future__ import annotations

from datetime import timedelta

import pytest

from cloud import models
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory, utc_now
from cloud.features.auth.service import (
    AuthError,
    authenticate,
    change_password,
    create_session,
    register_user,
    revoke_session,
    rotate_refresh,
    verify_email,
)
from cloud.tokens import verify_access_token

SETTINGS = generate_test_settings()
EMAIL = "owner@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _register_verified(session_factory):
    with session_factory() as session:
        user, token = register_user(
            session, email=EMAIL, password=PASSWORD, settings=SETTINGS
        )
        verify_email(session, raw_token=token)
        device = models.Device(user_id=user.id, public_key="pk-a")
        session.add(device)
        session.commit()
        return user.id, device.id


def _new_session(session_factory, user_id, device_id):
    with session_factory() as session:
        user = session.get(models.User, user_id)
        device = session.get(models.Device, device_id)
        issued = create_session(session, user=user, device=device, settings=SETTINGS)
        session.commit()
        return issued.access_token, issued.refresh_token


def _rotate(session_factory, raw_refresh):
    with session_factory() as session:
        issued = rotate_refresh(session, raw_refresh=raw_refresh, settings=SETTINGS)
        session.commit()
        return issued.access_token, issued.refresh_token


def test_register_then_verify_activates_the_account(session_factory):
    with session_factory() as session:
        user, token = register_user(
            session, email="New@Example.COM ", password=PASSWORD, settings=SETTINGS
        )
        assert user.status == "unverified"
        assert user.email == "new@example.com"  # normalized
        session.commit()
        user_id = user.id
    with session_factory() as session:
        verified = verify_email(session, raw_token=token)
        session.commit()
        assert verified.id == user_id
        assert verified.status == "active"


def test_duplicate_email_is_rejected(session_factory):
    _register_verified(session_factory)
    with session_factory() as session:
        with pytest.raises(AuthError) as error:
            register_user(session, email=EMAIL.upper(), password=PASSWORD, settings=SETTINGS)
    assert error.value.code == "email_taken"


def test_authenticate_paths(session_factory):
    user_id, _device = _register_verified(session_factory)
    with session_factory() as session:
        assert authenticate(session, email=EMAIL, password=PASSWORD).id == user_id
        with pytest.raises(AuthError) as wrong:
            authenticate(session, email=EMAIL, password="not the password")
        assert wrong.value.code == "invalid_credentials"


def test_unverified_account_cannot_authenticate(session_factory):
    with session_factory() as session:
        register_user(session, email=EMAIL, password=PASSWORD, settings=SETTINGS)
        session.commit()
    with session_factory() as session:
        with pytest.raises(AuthError) as error:
            authenticate(session, email=EMAIL, password=PASSWORD)
    assert error.value.code == "account_unverified"


def test_create_session_issues_a_valid_access_token_and_refresh(session_factory):
    user_id, device_id = _register_verified(session_factory)
    access, refresh = _new_session(session_factory, user_id, device_id)
    assert refresh  # opaque raw token returned once
    claims = verify_access_token(access, SETTINGS.signing_public_key)
    assert claims["typ"] == "access"
    assert claims["sub"] == user_id
    assert claims["device_id"] == device_id
    assert claims["exp"] > claims["iat"]


def test_rotation_issues_a_new_refresh_and_old_one_is_reuse(session_factory):
    user_id, device_id = _register_verified(session_factory)
    _access, refresh1 = _new_session(session_factory, user_id, device_id)
    _access2, refresh2 = _rotate(session_factory, refresh1)
    assert refresh2 != refresh1
    # Presenting the already-rotated refresh again is reuse.
    with session_factory() as session:
        with pytest.raises(AuthError) as error:
            rotate_refresh(session, raw_refresh=refresh1, settings=SETTINGS)
    assert error.value.code == "refresh_reuse"


def test_refresh_reuse_revokes_the_whole_family(session_factory):
    user_id, device_id = _register_verified(session_factory)
    _access, refresh1 = _new_session(session_factory, user_id, device_id)
    _access2, refresh2 = _rotate(session_factory, refresh1)
    # Trigger reuse with the old token → family revoked.
    with session_factory() as session:
        with pytest.raises(AuthError):
            rotate_refresh(session, raw_refresh=refresh1, settings=SETTINGS)
        session.commit()
    # The *current* refresh (refresh2) is now dead too — containment.
    with session_factory() as session:
        with pytest.raises(AuthError):
            rotate_refresh(session, raw_refresh=refresh2, settings=SETTINGS)


def test_logout_revokes_the_family(session_factory):
    user_id, device_id = _register_verified(session_factory)
    _access, refresh = _new_session(session_factory, user_id, device_id)
    with session_factory() as session:
        assert revoke_session(session, raw_refresh=refresh) is True
        session.commit()
    with session_factory() as session:
        with pytest.raises(AuthError):
            rotate_refresh(session, raw_refresh=refresh, settings=SETTINGS)


def test_expired_refresh_is_rejected(session_factory):
    user_id, device_id = _register_verified(session_factory)
    _access, refresh = _new_session(session_factory, user_id, device_id)
    future = utc_now() + timedelta(days=400)  # past the 30-day refresh TTL
    with session_factory() as session:
        with pytest.raises(AuthError) as error:
            rotate_refresh(session, raw_refresh=refresh, settings=SETTINGS, now=future)
    assert error.value.code == "refresh_expired"


def test_change_password_revokes_sessions_and_updates_hash(session_factory):
    user_id, device_id = _register_verified(session_factory)
    _access, refresh = _new_session(session_factory, user_id, device_id)
    with session_factory() as session:
        user = session.get(models.User, user_id)
        revoked = change_password(session, user=user, new_password="a-brand-new-password-9")
        session.commit()
        assert revoked >= 1
    with session_factory() as session:
        # Old refresh no longer rotates; old password no longer authenticates.
        with pytest.raises(AuthError):
            rotate_refresh(session, raw_refresh=refresh, settings=SETTINGS)
        with pytest.raises(AuthError):
            authenticate(session, email=EMAIL, password=PASSWORD)
        assert authenticate(session, email=EMAIL, password="a-brand-new-password-9").id == user_id
