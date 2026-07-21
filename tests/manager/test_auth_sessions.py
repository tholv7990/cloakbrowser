from __future__ import annotations

from datetime import timedelta

import pytest

from manager_backend.auth.sessions import (
    SessionPolicy,
    issue_session,
    revoke_all_sessions,
    validate_session,
)
from manager_backend.errors import ManagerError
from manager_backend.models import Owner, utc_now


def test_issue_session_stores_only_hashes(db_session_factory):
    session = db_session_factory()
    try:
        owner = Owner(email="owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        issued = issue_session(session, owner)

        assert issued.token not in issued.record.token_hash
        assert issued.csrf_token not in issued.record.csrf_hash
        assert len(issued.record.token_hash) == 64
        assert len(issued.record.csrf_hash) == 64
    finally:
        session.close()


def test_validate_session_accepts_valid_cookie_and_csrf(db_session_factory):
    session = db_session_factory()
    try:
        owner = Owner(email="owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        issued = issue_session(session, owner)

        result = validate_session(
            session,
            issued.token,
            csrf_token=issued.csrf_token,
            require_csrf=True,
        )
        assert result.owner.email == "owner@example.com"
    finally:
        session.close()


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_validate_session_rejects_missing_or_invalid_token(db_session_factory, token):
    session = db_session_factory()
    try:
        with pytest.raises(ManagerError) as error:
            validate_session(session, token)
        assert error.value.code == "authentication_required"
        assert error.value.status_code == 401
    finally:
        session.close()


def test_validate_session_rejects_bad_csrf(db_session_factory):
    session = db_session_factory()
    try:
        owner = Owner(email="owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        issued = issue_session(session, owner)
        with pytest.raises(ManagerError) as error:
            validate_session(session, issued.token, csrf_token="bad", require_csrf=True)
        assert error.value.code == "csrf_invalid"
        assert error.value.status_code == 403
    finally:
        session.close()


def test_validate_session_enforces_idle_expiry(db_session_factory):
    session = db_session_factory()
    try:
        owner = Owner(email="owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        issued = issue_session(session, owner)
        issued.record.last_seen_at = utc_now() - timedelta(minutes=31)
        session.commit()
        with pytest.raises(ManagerError) as error:
            validate_session(session, issued.token)
        assert error.value.code == "session_expired"
        assert issued.record.revoked_at is not None
    finally:
        session.close()


def test_validate_session_enforces_absolute_expiry(db_session_factory):
    session = db_session_factory()
    try:
        owner = Owner(email="owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        issued = issue_session(session, owner)
        issued.record.absolute_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
        with pytest.raises(ManagerError) as error:
            validate_session(session, issued.token)
        assert error.value.code == "session_expired"
    finally:
        session.close()


def test_revoke_all_sessions(db_session_factory):
    session = db_session_factory()
    try:
        owner = Owner(email="owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        first = issue_session(session, owner)
        second = issue_session(session, owner)
        assert revoke_all_sessions(session, owner.id) == 2
        assert first.record.revoked_at is not None
        assert second.record.revoked_at is not None
    finally:
        session.close()


def test_session_policy_defaults():
    policy = SessionPolicy()
    assert policy.idle_timeout == timedelta(minutes=30)
    assert policy.absolute_timeout == timedelta(hours=12)
