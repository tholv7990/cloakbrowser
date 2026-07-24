from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from datetime import datetime, timezone
import sqlite3

from alembic import command
from alembic.config import Config

import pytest
from sqlalchemy import func, select

from manager_backend.features.runtime.logs import (
    append_profile_log,
    list_profile_logs,
    tail_profile_logs,
)
from manager_backend.models import Profile, ProfileLogEntry


def _profile(session_factory) -> str:
    with session_factory() as session:
        profile = Profile(
            name="Runtime logs",
            fingerprint_seed=str(uuid4().int % 1_000_000_000_000_000_000),
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        return profile.id


def _append(session, profile_id, settings, event="runtime.ready", *, level="info", fields=None):
    return append_profile_log(
        session,
        profile_id,
        level,
        event,
        fields=fields,
        settings=settings,
    )


def _log_count(session, profile_id) -> int:
    return int(
        session.scalar(
            select(func.count(ProfileLogEntry.id)).where(ProfileLogEntry.profile_id == profile_id)
        )
        or 0
    )


def test_append_profile_log_keeps_the_newest_2000_entries(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    events = (
        "runtime.start_requested",
        "runtime.preflight_failed",
        "runtime.ready",
        "runtime.stop_requested",
        "runtime.crashed",
        "runtime.reconciled",
    )
    with db_session_factory() as session:
        entries = [
            _append(session, profile_id, settings, events[number % len(events)])
            for number in range(2002)
        ]

        assert _log_count(session, profile_id) == 2000
        remaining = list(
            session.scalars(
                select(ProfileLogEntry)
                .where(ProfileLogEntry.profile_id == profile_id)
                .order_by(ProfileLogEntry.created_at.desc(), ProfileLogEntry.id.desc())
            )
        )

    expected = sorted(entries, key=lambda entry: (entry.created_at, entry.id), reverse=True)[:2000]
    assert [(entry.id, entry.message) for entry in remaining] == [
        (entry.id, entry.message) for entry in expected
    ]


def test_list_profile_logs_paginates_newest_first(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session:
        _append(session, profile_id, settings, "runtime.start_requested")
        _append(session, profile_id, settings, "runtime.ready")
        _append(session, profile_id, settings, "runtime.crashed", level="error")
        page = list_profile_logs(session, profile_id, page=2, page_size=2)

    assert page.total == 3
    assert page.page == 2
    assert page.page_size == 2
    assert page.pages == 2
    assert [entry["event"] for entry in page.items] == ["runtime.start_requested"]


def test_append_profile_log_uses_allowlisted_runtime_event_templates(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    profile_path = settings.profile_root / profile_id / "user-data"
    expected = [
        ("runtime.start_requested", "Runtime start requested.", None),
        ("runtime.preflight_failed", "Runtime preflight failed.", None),
        ("runtime.process_started", f"Runtime process started at {profile_path}.", {"profile_path": str(profile_path)}),
        ("runtime.ready", "Runtime ready.", None),
        ("runtime.stop_requested", "Runtime stop requested.", None),
        ("runtime.exited", "Runtime exited with code 17.", {"exit_code": 17}),
        ("runtime.crashed", "Runtime crashed.", None),
        ("runtime.reconciled", "Runtime reconciled.", None),
    ]

    with db_session_factory() as session:
        entries = [
            _append(session, profile_id, settings, event, fields=fields)
            for event, _message, fields in expected
        ]

    assert [entry.event for entry in entries] == [event for event, _message, _fields in expected]
    assert [entry.message for entry in entries] == [message for _event, message, _fields in expected]


def test_append_profile_log_redacts_structured_paths_outside_its_profile_directory(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    outside_path = Path(settings.profile_root).parent / "outside" / "tokens.txt"

    with db_session_factory() as session:
        entry = _append(
            session,
            profile_id,
            settings,
            "runtime.process_started",
            fields={"profile_path": str(outside_path)},
        )

    assert str(outside_path) not in entry.message
    assert entry.message == "Runtime process started at [REDACTED_PATH]."


def test_append_profile_log_rejects_non_allowlisted_events(db_session_factory, settings):
    profile_id = _profile(db_session_factory)

    with db_session_factory() as session:
        with pytest.raises(ValueError, match="event"):
            _append(session, profile_id, settings, "runtime.custom")
        assert _log_count(session, profile_id) == 0


def test_append_profile_log_rejects_path_like_and_noncanonical_profile_ids(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    invalid_profile_ids = (
        r"..\..\outside",
        "../../outside",
        "profiles/../outside",
        "not-a-uuid",
        profile_id.upper(),
        f"{{{profile_id}}}",
        profile_id.replace("-", ""),
    )

    with db_session_factory() as session:
        for invalid_profile_id in invalid_profile_ids:
            with pytest.raises(ValueError, match="profile_id"):
                _append(
                    session,
                    invalid_profile_id,
                    settings,
                    "runtime.process_started",
                    fields={"profile_path": str(settings.profile_root / profile_id / "user-data")},
                )
        assert _log_count(session, profile_id) == 0
        assert session.scalar(select(func.count(ProfileLogEntry.id))) == 0


@pytest.mark.parametrize(
    "unsafe_input",
    [
        "cmd /c set SECRET=leak",
        "python -m package --api-key leak",
        'pwsh -Command "$env:SECRET"',
        'os.environ["SECRET"]',
        'os.getenv("SECRET")',
        "Authorization: Bearer access-token",
        "refresh_token=refresh-secret",
    ],
)
def test_append_profile_log_rejects_unsafe_free_form_input(
    db_session_factory, settings, unsafe_input
):
    profile_id = _profile(db_session_factory)

    with db_session_factory() as session:
        with pytest.raises(ValueError, match="fields"):
            _append(
                session,
                profile_id,
                settings,
                "runtime.crashed",
                level="error",
                fields={"message": unsafe_input},
            )
        assert _log_count(session, profile_id) == 0


def test_append_profile_log_has_no_message_argument(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session:
        with pytest.raises(TypeError):
            append_profile_log(
                session,
                profile_id,
                "error",
                "runtime.crashed",
                "arbitrary free-form message",
                settings=settings,
            )
        assert _log_count(session, profile_id) == 0


def test_list_profile_logs_rejects_page_size_above_200(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session, pytest.raises(ValueError, match="200"):
        list_profile_logs(session, profile_id, page_size=201)


def test_tail_profile_logs_uses_opaque_cursor_without_duplicates_or_skips(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session:
        first = _append(session, profile_id, settings, "runtime.start_requested")
        second = _append(session, profile_id, settings, "runtime.ready")
        third = _append(session, profile_id, settings, "runtime.crashed", level="error")
        initial = tail_profile_logs(
            session, profile_id, cursor=None, limit=2, secret="cursor-secret"
        )

    assert [item.id for item in initial.items] == [second.id, third.id]
    assert initial.reset is False
    assert initial.next_cursor
    assert profile_id not in initial.next_cursor
    assert first.id not in initial.next_cursor
    assert third.id not in initial.next_cursor

    with db_session_factory() as session:
        fourth = _append(session, profile_id, settings, "runtime.stop_requested")
        fifth = _append(session, profile_id, settings, "runtime.reconciled")
        next_page = tail_profile_logs(
            session,
            profile_id,
            cursor=initial.next_cursor,
            limit=1,
            secret="cursor-secret",
        )
        final_page = tail_profile_logs(
            session,
            profile_id,
            cursor=next_page.next_cursor,
            limit=2,
            secret="cursor-secret",
        )

    assert [item.id for item in next_page.items] == [fourth.id]
    assert [item.id for item in final_page.items] == [fifth.id]
    assert len({item.id for item in next_page.items + final_page.items}) == 2


def test_tail_profile_logs_resets_malformed_cross_profile_and_truncated_cursor(
    db_session_factory, settings
):
    first_profile = _profile(db_session_factory)
    second_profile = _profile(db_session_factory)
    with db_session_factory() as session:
        old = _append(session, first_profile, settings, "runtime.start_requested")
        _append(session, first_profile, settings, "runtime.ready")
        _append(session, second_profile, settings, "runtime.crashed", level="error")
        cursor = tail_profile_logs(
            session, first_profile, cursor=None, limit=2, secret="cursor-secret"
        ).next_cursor
        cross_profile = tail_profile_logs(
            session,
            second_profile,
            cursor=cursor,
            limit=10,
            secret="cursor-secret",
        )
        malformed = tail_profile_logs(
            session,
            first_profile,
            cursor="not-a-valid-cursor",
            limit=10,
            secret="cursor-secret",
        )
        session.delete(session.get(ProfileLogEntry, old.id))
        session.commit()

    with db_session_factory() as session:
        old_cursor = tail_profile_logs(
            session, first_profile, cursor=None, limit=1, secret="cursor-secret"
        ).next_cursor
        cursor_entry = session.scalar(
            select(ProfileLogEntry)
            .where(ProfileLogEntry.profile_id == first_profile)
            .order_by(ProfileLogEntry.created_at.desc(), ProfileLogEntry.id.desc())
        )
        session.delete(cursor_entry)
        session.commit()
    with db_session_factory() as session:
        truncated = tail_profile_logs(
            session,
            first_profile,
            cursor=old_cursor,
            limit=10,
            secret="cursor-secret",
        )

    assert cross_profile.reset is True
    assert malformed.reset is True
    assert truncated.reset is True


def test_profile_log_tail_api_is_bounded_authenticated_and_observes_concurrent_appends(
    client, auth_headers, settings
):
    profile = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Tail API"}
    ).json()
    profile_id = profile["id"]
    with client.app.state.session_factory() as session:
        _append(session, profile_id, settings, "runtime.start_requested")
    baseline = client.get(
        f"/api/v1/profiles/{profile_id}/logs/tail?limit=2", headers=auth_headers
    ).json()
    barrier = Barrier(4)

    def append_one():
        barrier.wait()
        with client.app.state.session_factory() as session:
            return _append(session, profile_id, settings, "runtime.ready").id

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(append_one) for _ in range(4)]
        appended = {future.result() for future in futures}

    initial = client.get(
        f"/api/v1/profiles/{profile_id}/logs/tail",
        headers=auth_headers,
        params={"cursor": baseline["next_cursor"], "limit": 2},
    )
    assert initial.status_code == 200
    body = initial.json()
    assert len(body["items"]) == 2
    assert body["reset"] is False
    assert body["next_cursor"]

    follow = client.get(
        f"/api/v1/profiles/{profile_id}/logs/tail",
        headers=auth_headers,
        params={"cursor": body["next_cursor"], "limit": 2},
    )
    assert follow.status_code == 200
    observed = {item["id"] for item in body["items"] + follow.json()["items"]}
    assert observed == appended

    too_large = client.get(
        f"/api/v1/profiles/{profile_id}/logs/tail?limit=201", headers=auth_headers
    )
    assert too_large.status_code == 422
    client.cookies.clear()
    assert client.get(f"/api/v1/profiles/{profile_id}/logs/tail").status_code == 401


def test_tail_uses_persistent_monotonic_sequence_when_timestamps_and_uuids_reverse(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    same_time = datetime(2026, 7, 22, tzinfo=timezone.utc)
    with db_session_factory() as session:
        first = _append(session, profile_id, settings, "runtime.ready")
        second = _append(session, profile_id, settings, "runtime.ready")
        first.id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        second.id = "00000000-0000-4000-8000-000000000001"
        first.created_at = second.created_at = same_time
        session.commit()
        initial = tail_profile_logs(
            session, profile_id, cursor=None, limit=1, secret="cursor-secret"
        )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [item.id for item in initial.items] == [second.id]

    with db_session_factory() as session:
        third = _append(session, profile_id, settings, "runtime.ready")
        third.created_at = same_time
        session.commit()
        follow = tail_profile_logs(
            session,
            profile_id,
            cursor=initial.next_cursor,
            limit=10,
            secret="cursor-secret",
        )
    assert third.sequence == 3
    assert [item.id for item in follow.items] == [third.id]


def test_runtime_log_sequence_migration_backfills_and_downgrades(tmp_path, monkeypatch):
    data_root = tmp_path / "runtime-log-sequence-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "0010_diagnostics")
    database = data_root / "manager.db"
    profile_id = "00000000-0000-4000-8000-000000000010"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO profiles (id,name,notes,pinned,fingerprint_seed,fingerprint_preset,"
            "fingerprint_revision,fingerprint_config_hash,browser_version_mode,"
            "user_agent_mode,location_json,window_json,behavior_json,"
            "test_proxy_before_launch,total_runtime_seconds,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                profile_id,
                "Migrated logs",
                "",
                0,
                "99887766",
                "consistent",
                1,
                "a" * 64,
                "installed",
                "automatic",
                '{"geo_mode":"system"}',
                '{"mode":"maximized"}',
                '{}',
                1,
                0,
                "2026-07-22 00:00:00",
                "2026-07-22 00:00:00",
            ),
        )
        for entry_id in (
            "ffffffff-ffff-4fff-8fff-ffffffffffff",
            "00000000-0000-4000-8000-000000000001",
        ):
            connection.execute(
                "INSERT INTO profile_log_entries "
                "(id,profile_id,created_at,level,event,message) VALUES (?,?,?,?,?,?)",
                (
                    entry_id,
                    profile_id,
                    "2026-07-22 00:00:00",
                    "info",
                    "runtime.ready",
                    "Runtime ready.",
                ),
            )
        connection.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id,sequence FROM profile_log_entries ORDER BY sequence"
        ).fetchall()
        next_sequence = connection.execute(
            "SELECT next_sequence FROM profile_log_sequences WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0]
        indexes = {row[1]: row for row in connection.execute("PRAGMA index_list(profile_log_entries)")}
    assert rows == [
        ("00000000-0000-4000-8000-000000000001", 1),
        ("ffffffff-ffff-4fff-8fff-ffffffffffff", 2),
    ]
    assert next_sequence == 3
    assert indexes["uq_profile_log_entries_profile_sequence"][2] == 1

    command.downgrade(config, "0010_diagnostics")
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(profile_log_entries)")}
        counter_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='profile_log_sequences'"
        ).fetchone()
    assert "sequence" not in columns
    assert counter_table is None
