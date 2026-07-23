from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from manager_backend.features.media.service import list_assets
from manager_backend.features.profiles.service import list_profiles
from manager_backend.features.proxies.service import list_proxies
from manager_backend.features.resources.service import list_sessions
from manager_backend.features.resources import service as resource_service
from manager_backend.features.runtime import snapshots as runtime_snapshots
from manager_backend.features.runtime.snapshots import load_latest_runtimes
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


def test_latest_runtime_snapshot_uses_bounded_sqlite_work() -> None:
    engine = _engine()
    with Session(engine) as session:
        profiles = [_profile(index) for index in range(100)]
        session.add_all(profiles)
        session.flush()
        for runtime_index in range(100):
            session.add_all(
                [
                    RuntimeSession(
                        profile_id=profile.id,
                        state="stopped",
                        last_message="stopped",
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
                        + timedelta(minutes=runtime_index),
                    )
                    for profile in profiles
                ]
            )
        session.commit()
        session.expunge_all()

        callbacks = 0

        def count_vm_steps() -> int:
            nonlocal callbacks
            callbacks += 1
            return 0

        raw = session.connection().connection.driver_connection
        assert isinstance(raw, sqlite3.Connection)
        raw.set_progress_handler(count_vm_steps, 100)
        try:
            runtimes, _ = load_latest_runtimes(session)
        finally:
            raw.set_progress_handler(None, 0)

    assert len(runtimes) == 100
    assert callbacks < 2_000


def test_resource_snapshot_uses_constant_profile_lookup_queries(monkeypatch) -> None:
    engine = _engine()

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def cpu_percent(self, interval=None) -> float:
            return 1.0

        def memory_info(self):
            return type("Memory", (), {"rss": 1024})()

        def is_running(self) -> bool:
            return True

    monkeypatch.setattr(resource_service, "_cache", None)
    monkeypatch.setattr(resource_service, "_tree", lambda pid: [Process(pid)])

    with Session(engine) as session:
        profiles = [_profile(index) for index in range(100)]
        session.add_all(profiles)
        session.flush()
        session.add_all(
            [
                RuntimeSession(
                    profile_id=profile.id,
                    state="running",
                    last_message="running",
                    browser_pid=10_000 + index,
                )
                for index, profile in enumerate(profiles)
            ]
        )
        session.commit()
        session.expunge_all()

        with statement_counter(engine) as statements:
            snapshot = resource_service.build_snapshot(session)

    assert len(snapshot["profiles"]) == 100
    assert len(statements) <= 2


def test_runtime_snapshot_cache_skips_loader_when_database_is_unchanged(
    monkeypatch,
) -> None:
    engine = _engine()
    calls = 0
    original = runtime_snapshots.load_latest_runtimes

    def counted(session: Session):
        nonlocal calls
        calls += 1
        return original(session)

    monkeypatch.setattr(runtime_snapshots, "load_latest_runtimes", counted)
    cache_type = getattr(runtime_snapshots, "RuntimeSnapshotCache", None)
    assert cache_type is not None
    cache = cache_type()

    with Session(engine) as session:
        profile = _profile(1)
        session.add(profile)
        session.flush()
        runtime = RuntimeSession(
            profile_id=profile.id,
            state="running",
            last_message="running",
        )
        session.add(runtime)
        session.commit()

        first = cache.poll(session)
        second = cache.poll(session)
        runtime.last_message = "changed"
        session.commit()
        third = cache.poll(session)

    assert first.changed is True
    assert second.changed is False
    assert third.changed is True
    assert calls == 2
