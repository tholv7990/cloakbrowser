from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from .config import ManagerSettings


_PERFORMANCE_INDEXES = frozenset(
    {
        "ix_profiles_proxy_id",
        "ix_runtime_sessions_profile_created_at",
        "ix_runtime_sessions_profile_state",
        "ix_runtime_sessions_created_at_id",
        "ix_runtime_sessions_updated_at",
        "ix_profile_media_assets_media_profile",
    }
)


def create_engine_for(settings: ManagerSettings) -> Engine:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    database_path = settings.data_root / "manager.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def ensure_performance_indexes(engine: Engine) -> None:
    """Idempotently bridge legacy create_all databases to the indexed schema."""
    from .models import Base

    indexes = (
        index
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name in _PERFORMANCE_INDEXES
    )
    with engine.begin() as connection:
        for index in indexes:
            index.create(connection, checkfirst=True)


@contextmanager
def _alembic_config(data_root: Path) -> Iterator["object"]:
    """Alembic config pinned to this database (env.py reads CLOAK_MANAGER_DATA_ROOT).

    The env var is set for the duration of the migration only and restored after,
    so running against one database never leaks its data root to other callers.
    """
    from alembic.config import Config

    here = Path(__file__).resolve().parent
    previous = os.environ.get("CLOAK_MANAGER_DATA_ROOT")
    os.environ["CLOAK_MANAGER_DATA_ROOT"] = str(data_root)
    try:
        config = Config(str(here / "alembic.ini"))
        config.set_main_option("script_location", str(here / "migrations"))
        yield config
    finally:
        if previous is None:
            os.environ.pop("CLOAK_MANAGER_DATA_ROOT", None)
        else:
            os.environ["CLOAK_MANAGER_DATA_ROOT"] = previous


def apply_schema(engine: Engine, data_root: Path) -> None:
    """Bring the database to the latest schema, with Alembic owning *evolution*.

    - An already-managed database is upgraded to head, so column/table changes in
      new migrations actually apply (plain create_all cannot ALTER existing tables
      — the class of bug this replaces).
    - A brand-new (or legacy create_all) database is built from the models and
      stamped at head. This keeps fresh builds instant — the test suite creates a
      database per case — while still marking it managed so future migrations run.
    """
    from alembic import command
    from .models import Base

    with _alembic_config(data_root) as config:
        if inspect(engine).has_table("alembic_version"):
            command.upgrade(config, "head")
        else:
            Base.metadata.create_all(engine)
            ensure_performance_indexes(engine)
            command.stamp(config, "head")


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
