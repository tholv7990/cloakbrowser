"""create-admin bootstrap: creates the super-admin, promotes idempotently."""

from __future__ import annotations

from sqlalchemy import select

from cloud import models
from cloud.admin import ensure_admin
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.passwords import verify_password


def test_create_admin_creates_then_promotes_the_same_account(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        user = ensure_admin(
            session, email="Root@UsePlasma.app", password="first-password-123"
        )
        session.commit()
        assert user.role == "admin"
        assert user.status == "active"

    # Re-running with different case must not create a second account; it
    # resets the password on the existing one.
    with factory() as session:
        ensure_admin(
            session, email="root@useplasma.app", password="second-password-456"
        )
        session.commit()

    with factory() as session:
        rows = session.scalars(select(models.User)).all()
        assert len(rows) == 1
        assert rows[0].role == "admin"
        assert verify_password(rows[0].password_hash, "second-password-456")
