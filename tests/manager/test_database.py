from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from manager_backend.config import ManagerSettings
from manager_backend.db import create_engine_for
from manager_backend.models import Base, Folder, Profile, Tag


def _database(tmp_path):
    settings = ManagerSettings(
        data_root=tmp_path / "manager-data",
        install_token="test-local-token",
    )
    engine = create_engine_for(settings)
    Base.metadata.create_all(engine)
    return engine


def test_sqlite_uses_wal_and_foreign_keys(tmp_path):
    engine = _database(tmp_path)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_profile_name_and_unsigned_seed_persist(tmp_path):
    engine = _database(tmp_path)

    with Session(engine) as session:
        profile = Profile(
            name="Account A",
            windows_persona="windows_11",
            fingerprint_seed="18446744073709551615",
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id
        session.expire_all()

        persisted = session.get(Profile, profile_id)
        assert persisted is not None
        assert persisted.fingerprint_seed == "18446744073709551615"
        assert persisted.identity == {}
        assert persisted.hardware == {}
        assert persisted.advanced == {}


def test_profile_folder_foreign_key_is_enforced(tmp_path):
    engine = _database(tmp_path)

    with Session(engine) as session:
        session.add(
            Profile(
                name="Orphan",
                folder_id="00000000-0000-0000-0000-000000000000",
                windows_persona="windows_11",
                fingerprint_seed="1",
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("Expected profile folder foreign key to be enforced")


def test_catalog_names_are_unique(tmp_path):
    engine = _database(tmp_path)

    with Session(engine) as session:
        session.add_all([Folder(name="KYC"), Folder(name="KYC")])
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("Expected duplicate folder name to fail")


def test_profile_tag_join_uses_composite_primary_key(tmp_path):
    engine = _database(tmp_path)

    with Session(engine) as session:
        profile = Profile(
            name="Tagged",
            windows_persona="windows_10",
            fingerprint_seed="42",
        )
        tag = Tag(name="KYC", color="#2563EB")
        profile.tags.append(tag)
        session.add(profile)
        session.commit()

        count = session.execute(text("SELECT COUNT(*) FROM profile_tags")).scalar_one()
        assert count == 1
