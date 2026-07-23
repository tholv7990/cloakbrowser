"""Database plumbing for the cloud control plane.

PostgreSQL in production (via ``PLASMA_CLOUD_DATABASE_URL``); SQLite is used by the
test suite. Types in ``models.py`` are kept portable so the same models run on both
— production-only concerns (schema evolution) go through Alembic, mirroring the
desktop's discipline.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    """A globally-unique id as a canonical UUID4 string (portable PK)."""
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def database_url() -> str:
    """Resolve the DB URL. Production must set ``PLASMA_CLOUD_DATABASE_URL`` to a
    PostgreSQL DSN; there is no insecure default so a misconfigured deploy fails
    loudly instead of silently using a throwaway store."""
    url = os.environ.get("PLASMA_CLOUD_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "PLASMA_CLOUD_DATABASE_URL is not set (expected a PostgreSQL DSN)"
        )
    return url


def create_engine_for(url: str) -> Engine:
    """Build an engine. SQLite (tests) gets foreign-key enforcement turned on so
    the model's FK/ON DELETE rules are actually exercised, matching Postgres."""
    connect_args = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        connect_args["check_same_thread"] = False
    engine = create_engine(url, future=True, connect_args=connect_args)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
