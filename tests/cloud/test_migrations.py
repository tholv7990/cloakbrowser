from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from cloud.db import Base


def _alembic_config() -> Config:
    config = Config("cloud/alembic.ini")
    config.set_main_option("script_location", "cloud/migrations")
    return config


def test_migration_head_builds_the_model_schema(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setenv("PLASMA_CLOUD_DATABASE_URL", url)

    command.upgrade(_alembic_config(), "head")

    engine = create_engine(url)
    try:
        migrated = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    expected = set(Base.metadata.tables) | {"alembic_version"}
    # The migration creates exactly the tables the models declare (no drift).
    assert migrated == expected


def test_migration_downgrades_cleanly(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setenv("PLASMA_CLOUD_DATABASE_URL", url)
    config = _alembic_config()

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    try:
        remaining = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # Only alembic's own bookkeeping table survives a full downgrade.
    assert remaining <= {"alembic_version"}
