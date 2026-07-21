from __future__ import annotations

from pathlib import Path

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.profiles import directories
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


def test_resolve_profile_directory_rejects_an_escaped_resolved_target_without_symlinks(
    monkeypatch, settings
):
    profiles_root = settings.profile_root.resolve()
    escaped_path = settings.data_root.parent / "escaped-profile-directory"

    def resolve_with_escaped_target(path: Path) -> Path:
        if path == profiles_root / PROFILE_ID:
            return escaped_path
        return path.resolve(strict=False)

    monkeypatch.setattr(
        directories, "_resolve_path", resolve_with_escaped_target, raising=False
    )

    with pytest.raises(ManagerError) as raised:
        resolve_profile_directory(settings, PROFILE_ID)

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


def _create_profile(client, auth_headers) -> dict:
    response = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Directory API"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_open_directory_route_uses_the_derived_path_and_returns_it(
    client, auth_headers, monkeypatch
):
    profile = _create_profile(client, auth_headers)
    opened: list[Path] = []
    monkeypatch.setattr(
        "manager_backend.features.profiles.routes.open_profile_directory", opened.append
    )

    response = client.post(
        f"/api/v1/profiles/{profile['id']}/open-directory", headers=auth_headers
    )

    expected = (client.app.state.settings.profile_root / profile["id"]).resolve()
    assert response.status_code == 200, response.text
    assert response.json() == {"profile_directory": str(expected)}
    assert opened == [expected]


def test_open_directory_route_rejects_unauthenticated_and_invalid_mutations_before_opening(
    client, auth_headers, monkeypatch
):
    profile = _create_profile(client, auth_headers)
    opened: list[Path] = []
    monkeypatch.setattr(
        "manager_backend.features.profiles.routes.open_profile_directory", opened.append
    )
    endpoint = f"/api/v1/profiles/{profile['id']}/open-directory"

    missing_csrf = client.post(endpoint, headers={"Origin": auth_headers["Origin"]})
    bad_origin = client.post(
        endpoint,
        headers={"Origin": "http://untrusted.example", "X-CSRF-Token": auth_headers["X-CSRF-Token"]},
    )
    client.cookies.clear()
    unauthenticated = client.post(endpoint, headers=auth_headers)

    assert missing_csrf.status_code == 403
    assert bad_origin.status_code == 403
    assert unauthenticated.status_code == 401
    assert opened == []


def test_open_directory_route_declares_all_manager_error_envelopes(client):
    responses = client.app.openapi()["paths"][
        "/api/v1/profiles/{profile_id}/open-directory"
    ]["post"]["responses"]

    for status_code in ("400", "404", "500", "501"):
        assert responses[status_code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
