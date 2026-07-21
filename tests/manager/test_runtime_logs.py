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


def test_append_profile_log_keeps_the_newest_2000_entries(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session:
        for number in range(2002):
            append_profile_log(
                session,
                profile_id,
                "info",
                "runtime.ready",
                f"entry-{number}",
                settings=settings,
            )

        total = session.scalar(
            select(func.count(ProfileLogEntry.id)).where(ProfileLogEntry.profile_id == profile_id)
        )
        assert total == 2000
        messages = list(
            session.scalars(
                select(ProfileLogEntry.message)
                .where(ProfileLogEntry.profile_id == profile_id)
                .order_by(ProfileLogEntry.created_at.asc(), ProfileLogEntry.id.asc())
            )
        )
        assert "entry-0" not in messages
        assert "entry-1" not in messages
        assert "entry-2001" in messages


def test_list_profile_logs_paginates_newest_first(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session:
        for number in range(3):
            append_profile_log(
                session,
                profile_id,
                "info",
                "runtime.ready",
                f"entry-{number}",
                settings=settings,
            )

        page = list_profile_logs(session, profile_id, page=2, page_size=2)

    assert page.total == 3
    assert page.page == 2
    assert page.page_size == 2
    assert page.pages == 2
    assert [entry["message"] for entry in page.items] == ["entry-0"]


def test_append_profile_log_allows_paths_inside_its_profile_directory(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    allowed_path = settings.profile_root / profile_id / "user-data" / "Preferences"

    with db_session_factory() as session:
        entry = append_profile_log(
            session,
            profile_id,
            "info",
            "runtime.ready",
            f"Using {allowed_path}",
            settings=settings,
        )

    assert str(allowed_path) in entry.message


def test_append_profile_log_redacts_secrets_and_unrelated_absolute_paths(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    outside_path = Path(settings.profile_root).parent / "outside" / "tokens.txt"
    message = (
        "proxy=socks5://alice:proxy-password@proxy.example:1080 "
        "license=cb_license-secret-123 "
        "Cookie: session=browser-session-secret; theme=dark "
        f"read {outside_path}"
    )

    with db_session_factory() as session:
        entry = append_profile_log(
            session,
            profile_id,
            "error",
            "runtime.crashed",
            message,
            settings=settings,
        )

    for secret in (
        "alice",
        "proxy-password",
        "cb_license-secret-123",
        "browser-session-secret",
        str(outside_path),
    ):
        assert secret not in entry.message
    assert "[REDACTED_URL]" in entry.message
    assert "[REDACTED_LICENSE]" in entry.message
    assert "[REDACTED_TOKEN]" in entry.message
    assert "[REDACTED_PATH]" in entry.message


def test_append_profile_log_rejects_non_event_identifiers(db_session_factory, settings):
    profile_id = _profile(db_session_factory)

    with db_session_factory() as session, pytest.raises(ValueError, match="event"):
        append_profile_log(
            session,
            profile_id,
            "error",
            "runtime.crashed password=event-secret",
            "browser crashed",
            settings=settings,
        )

    with db_session_factory() as session:
        assert session.scalar(
            select(func.count(ProfileLogEntry.id)).where(ProfileLogEntry.profile_id == profile_id)
        ) == 0


def test_append_profile_log_redacts_credentials_environment_and_command_lines(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    message = (
        "password=generic-password api_key: generic-api-key "
        "environment={'CUSTOM_VALUE': 'environment-secret', 'PATH': 'C:/private/bin'} "
        "os.environ={'CUSTOM_VALUE': 'process-environment-secret'} "
        "command line: C:/private/browser.exe --proxy-server=socks5://user:pass@proxy.test"
    )

    with db_session_factory() as session:
        entry = append_profile_log(
            session,
            profile_id,
            "error",
            "runtime.crashed",
            message,
            settings=settings,
        )

    for secret in (
        "generic-password",
        "generic-api-key",
        "environment-secret",
        "process-environment-secret",
        "C:/private/bin",
        "C:/private/browser.exe",
        "proxy.test",
    ):
        assert secret not in entry.message
    assert "[REDACTED_CREDENTIAL]" in entry.message
    assert "[REDACTED_ENVIRONMENT]" in entry.message
    assert "[REDACTED_COMMAND]" in entry.message


def test_append_profile_log_redacts_unlabelled_relative_command_lines(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)

    with db_session_factory() as session:
        entry = append_profile_log(
            session,
            profile_id,
            "error",
            "runtime.crashed",
            "browser.exe --remote-debugging-port=9222 --proxy-server=socks5://user:pass@proxy.test",
            settings=settings,
        )

    assert "browser.exe" not in entry.message
    assert "9222" not in entry.message
    assert "proxy.test" not in entry.message
    assert entry.message == "[REDACTED_COMMAND]"


def test_append_profile_log_redacts_paths_under_an_untrusted_root(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    untrusted_root = settings.data_root.parent / "untrusted-manager" / "profiles"
    supplied_path = untrusted_root / profile_id / "user-data" / "Preferences"

    with db_session_factory() as session:
        entry = append_profile_log(
            session,
            profile_id,
            "info",
            "runtime.ready",
            f"Using {supplied_path}",
            settings=settings,
        )

    assert str(supplied_path) not in entry.message
    assert "[REDACTED_PATH]" in entry.message


def test_append_profile_log_redacts_unc_paths(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    unc_path = r"\\untrusted-server\profiles\secret\Preferences"

    with db_session_factory() as session:
        entry = append_profile_log(
            session,
            profile_id,
            "info",
            "runtime.ready",
            f"Using {unc_path}",
            settings=settings,
        )

    assert unc_path not in entry.message
    assert "[REDACTED_PATH]" in entry.message


def test_list_profile_logs_rejects_page_size_above_200(db_session_factory, settings):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session, pytest.raises(ValueError, match="200"):
        list_profile_logs(session, profile_id, page_size=201)
