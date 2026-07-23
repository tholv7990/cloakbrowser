from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import ManagerSettings


_PERFORMANCE_INDEXES = frozenset(
    {
        "ix_profiles_proxy_id",
        "ix_runtime_sessions_profile_created_at",
        "ix_runtime_sessions_created_at_id",
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
