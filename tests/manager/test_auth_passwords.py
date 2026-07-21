from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from manager_backend.auth.passwords import hash_password, verify_password
from manager_backend.auth.schemas import OwnerSetupRequest
from manager_backend.config import ManagerSettings
from manager_backend.db import create_engine_for
from manager_backend.models import AuthSession, Base, Owner


def test_setup_normalizes_email():
    request = OwnerSetupRequest(email="  Owner@Example.COM ", password="long secure password")

    assert request.email == "owner@example.com"


@pytest.mark.parametrize(
    "password",
    ["short", "            ", "contains\x00null", "a" * 1025],
)
def test_setup_rejects_invalid_password(password):
    with pytest.raises(ValidationError):
        OwnerSetupRequest(email="owner@example.com", password=password)


def test_password_is_argon2id_hashed_and_verifiable():
    encoded = hash_password("long secure password")

    assert encoded.startswith("$argon2id$")
    assert "long secure password" not in encoded
    assert verify_password(encoded, "long secure password") is True
    assert verify_password(encoded, "wrong secure password") is False


def test_owner_table_enforces_singleton(tmp_path):
    engine = create_engine_for(
        ManagerSettings(data_root=tmp_path, install_token="test-local-token")
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Owner(email="first@example.com", password_hash=hash_password("first secure password")),
                Owner(email="second@example.com", password_hash=hash_password("second secure password")),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_auth_models_have_no_plaintext_secret_columns():
    owner_columns = set(Owner.__table__.columns.keys())
    session_columns = set(AuthSession.__table__.columns.keys())

    assert "password" not in owner_columns
    assert "session_token" not in session_columns
    assert "csrf_token" not in session_columns
    assert {"password_hash"} <= owner_columns
    assert {"token_hash", "csrf_hash"} <= session_columns
