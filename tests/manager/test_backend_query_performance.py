from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from manager_backend.features.media.service import list_assets
from manager_backend.features.profiles.service import list_profiles
from manager_backend.features.proxies.service import list_proxies
from manager_backend.features.resources.service import list_sessions
from manager_backend.models import (
    Base,
    MediaAsset,
    Profile,
    Proxy,
    RuntimeSession,
    profile_media_assets,
)


@contextmanager
def statement_counter(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def before_cursor_execute(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def _engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _profile(index: int, *, proxy_id: str | None = None) -> Profile:
    return Profile(
        name=f"profile-{index:04}",
        fingerprint_seed=f"{index:020x}",
        fingerprint_config_hash="0" * 64,
        proxy_id=proxy_id,
    )


def test_proxy_list_uses_constant_statement_count() -> None:
    engine = _engine()
    with Session(engine) as session:
        proxies = [
            Proxy(label=f"proxy-{index:04}", scheme="http", host="127.0.0.1", port=8000)
            for index in range(100)
        ]
        session.add_all(proxies)
        session.flush()
        session.add_all([_profile(index, proxy_id=proxy.id) for index, proxy in enumerate(proxies)])
        session.commit()

        with statement_counter(engine) as statements:
            rows = list_proxies(session)

    assert len(rows) == 100
    assert all(row["assigned_profile_count"] == 1 for row in rows)
    assert len(statements) <= 3


def test_media_list_uses_constant_statement_count() -> None:
    engine = _engine()
    with Session(engine) as session:
        profiles = [_profile(index) for index in range(100)]
        assets = [
            MediaAsset(
                name=f"asset-{index:04}",
                kind="camera",
                format="video/mp4",
                size_bytes=0,
            )
            for index in range(100)
        ]
        session.add_all([*profiles, *assets])
        session.flush()
        session.execute(
            profile_media_assets.insert(),
            [
                {"profile_id": profile.id, "media_asset_id": asset.id}
                for profile, asset in zip(profiles, assets, strict=True)
            ],
        )
        session.commit()

        with statement_counter(engine) as statements:
            rows = list_assets(session)

    assert len(rows) == 100
    assert all(row["assigned_profile_count"] == 1 for row in rows)
    assert len(statements) <= 3


def test_profile_list_does_not_materialize_terminal_runtime_history() -> None:
    engine = _engine()
    with Session(engine) as session:
        profile = _profile(1)
        session.add(profile)
        session.flush()
        session.add_all(
            [
                RuntimeSession(
                    profile_id=profile.id,
                    state="stopped",
                    last_message="stopped",
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
                )
                for index in range(100)
            ]
        )
        session.add(
            RuntimeSession(profile_id=profile.id, state="running", last_message="running")
        )
        session.commit()
        session.expunge_all()

        with statement_counter(engine) as statements:
            result = list_profiles(
                session,
                query=None,
                folder_id=None,
                tag_id=None,
                workflow_status_id=None,
                pinned=None,
                sort="name",
                page=1,
                page_size=100,
            )
        loaded_runtimes = [
            value for value in session.identity_map.values() if isinstance(value, RuntimeSession)
        ]

    assert result["items"][0]["runtime_state"] == "running"
    assert len(loaded_runtimes) <= 1
    runtime_loads = [
        statement
        for statement in statements
        if "runtime_sessions" in statement and statement.lstrip().startswith("SELECT")
    ]
    assert len(runtime_loads) == 1
    assert "runtime_sessions.state IN" in runtime_loads[0]


def test_session_history_uses_constant_statement_count() -> None:
    engine = _engine()
    with Session(engine) as session:
        profiles = [_profile(index) for index in range(100)]
        session.add_all(profiles)
        session.flush()
        session.add_all(
            [
                RuntimeSession(
                    profile_id=profile.id,
                    state="stopped",
                    last_message="stopped",
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
                    + timedelta(minutes=index),
                )
                for index, profile in enumerate(profiles)
            ]
        )
        session.commit()
        session.expunge_all()

        with statement_counter(engine) as statements:
            rows = list_sessions(session, 100)

    assert len(rows) == 100
    assert len(statements) <= 2
