from __future__ import annotations

from pathlib import Path

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.profiles.directories import (
    open_profile_directory,
    resolve_profile_directory,
)


PROFILE_ID = "123e4567-e89b-12d3-a456-426614174000"


def test_resolve_profile_directory_derives_the_canonical_manager_owned_path(settings):
    directory = resolve_profile_directory(settings, PROFILE_ID)

    assert directory == (settings.data_root / "profiles" / PROFILE_ID).resolve()


@pytest.mark.parametrize(
    "profile_id",
    [
        "../../outside",
        r"..\\..\\outside",
        "not-a-uuid",
        PROFILE_ID.upper(),
        f"{{{PROFILE_ID}}}",
        PROFILE_ID.replace("-", ""),
    ],
)
def test_resolve_profile_directory_rejects_traversal_and_noncanonical_ids(settings, profile_id):
    with pytest.raises(ManagerError) as raised:
        resolve_profile_directory(settings, profile_id)

    assert raised.value.code == "profile_directory_invalid"


def test_resolve_profile_directory_rejects_a_symlink_that_escapes_the_profiles_root(
    settings, tmp_path
):
    profiles_root = settings.profile_root
    profiles_root.mkdir(parents=True)
    try:
        (profiles_root / PROFILE_ID).symlink_to(
            tmp_path / "outside", target_is_directory=True
        )
    except OSError as error:
        pytest.skip(f"Windows symlink creation is unavailable: {error.winerror}")

    with pytest.raises(ManagerError) as raised:
        resolve_profile_directory(settings, PROFILE_ID)

    assert raised.value.code == "profile_directory_invalid"


def test_open_profile_directory_creates_the_directory_and_uses_the_injected_opener(
    settings,
):
    opened: list[Path] = []
    directory = resolve_profile_directory(settings, PROFILE_ID)

    open_profile_directory(directory, opener=opened.append)

    assert directory.is_dir()
    assert opened == [directory]


def test_open_profile_directory_rejects_non_windows_hosts(monkeypatch, settings):
    directory = resolve_profile_directory(settings, PROFILE_ID)
    monkeypatch.setattr("manager_backend.features.profiles.directories.os.name", "posix")

    with pytest.raises(ManagerError) as raised:
        open_profile_directory(directory, opener=lambda _path: None)

    assert raised.value.code == "directory_open_not_supported"


def test_open_profile_directory_sanitizes_operating_system_failures(settings):
    directory = resolve_profile_directory(settings, PROFILE_ID)

    def failing_opener(_path: Path) -> None:
        raise OSError("C:\\Users\\Admin\\secret.txt")

    with pytest.raises(ManagerError) as raised:
        open_profile_directory(directory, opener=failing_opener)

    assert raised.value.code == "directory_open_failed"
    assert "secret.txt" not in raised.value.message
