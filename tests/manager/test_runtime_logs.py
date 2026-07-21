from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from manager_backend.features.runtime.logs import append_profile_log, list_profile_logs
from manager_backend.models import Profile, ProfileLogEntry


def _profile(session_factory) -> str:
    with session_factory() as session:
        profile = Profile(
            name="Runtime logs",
            fingerprint_seed="123456789",
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
