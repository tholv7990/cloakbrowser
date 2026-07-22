from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.extensions import service
from manager_backend.features.extensions.filesystem import UnsafeManifestPath
from manager_backend.models import Extension


class SwapDetectedFilesystem:
    def __init__(self):
        self.approved = None

    def read_manifest(self, approved, maximum_bytes):
        self.approved = approved
        raise UnsafeManifestPath


def test_injected_filesystem_race_detection_fails_closed_without_persisting(
    db_session_factory, settings, tmp_path, monkeypatch
):
    directory = tmp_path / "race"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "Safe", "version": "1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_temporary_roots", lambda: ())
    monkeypatch.setattr(service, "_system_roots", lambda: ())
    filesystem = SwapDetectedFilesystem()

    with db_session_factory() as session:
        with pytest.raises(ManagerError) as caught:
            service.register_extension(
                session, settings, str(directory), filesystem=filesystem
            )
        assert session.query(Extension).count() == 0

    assert caught.value.code == "extension_path_forbidden"
    assert filesystem.approved.path == directory.resolve()


def test_ancestor_reparse_component_is_detected_without_link_privileges(
    tmp_path, monkeypatch
):
    ancestor = (tmp_path / "ancestor").absolute()
    target = ancestor / "extension" / "manifest.json"

    def fake_lstat(path):
        return SimpleNamespace(
            st_file_attributes=(
                service._REPARSE_POINT if path == ancestor else 0
            )
        )

    monkeypatch.setattr(service.os, "lstat", fake_lstat)
    monkeypatch.setattr(service.Path, "is_symlink", lambda _path: False)

    assert service._path_has_reparse_component(target) is True


def test_native_handle_reader_returns_bounded_manifest_from_exact_directory(
    settings, tmp_path, monkeypatch
):
    directory = tmp_path / "native"
    directory.mkdir()
    expected = json.dumps(
        {"manifest_version": 3, "name": "Native", "version": "1"}
    ).encode()
    (directory / "manifest.json").write_bytes(expected)
    monkeypatch.setattr(service, "_temporary_roots", lambda: ())
    monkeypatch.setattr(service, "_system_roots", lambda: ())
    approved = service._canonical_directory(settings, str(directory))

    result = service.DEFAULT_MANIFEST_FILESYSTEM.read_manifest(approved, len(expected))

    assert result == expected


def test_native_handle_reader_rejects_manifest_over_limit_before_content_read(
    settings, tmp_path, monkeypatch
):
    directory = tmp_path / "bounded"
    directory.mkdir()
    (directory / "manifest.json").write_bytes(b"x" * 33)
    monkeypatch.setattr(service, "_temporary_roots", lambda: ())
    monkeypatch.setattr(service, "_system_roots", lambda: ())
    approved = service._canonical_directory(settings, str(directory))

    with pytest.raises(service.ManifestTooLarge):
        service.DEFAULT_MANIFEST_FILESYSTEM.read_manifest(approved, 32)
