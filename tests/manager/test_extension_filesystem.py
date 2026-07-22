from __future__ import annotations

import errno
import json
import stat
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.extensions import service
from manager_backend.features.extensions.filesystem import (
    ApprovedDirectory,
    ManifestReadFailure,
    SecureManifestFilesystem,
    UnsafeManifestPath,
)
from manager_backend.models import Extension


class SwapDetectedFilesystem:
    def __init__(self):
        self.approved = None

    def read_manifest(self, approved, maximum_bytes):
        self.approved = approved
        raise UnsafeManifestPath


class RecordingFilesystem:
    def __init__(self):
        self.called = False

    def read_manifest(self, approved, maximum_bytes):
        self.called = True
        raise AssertionError("handle reader must not see a resolved network path")


class ResolveLocalToUnc:
    def __init__(self):
        self.network_checks = []

    def is_network(self, supplied, path):
        self.network_checks.append((supplied, path))
        return str(path).replace("/", "\\").startswith("\\\\")

    def resolve(self, _path):
        return Path(r"\\server\share\swapped-extension")


class ResolveToCommaPath:
    def __init__(self, target):
        self.target = target

    def is_network(self, _supplied, _path):
        return False

    def resolve(self, _path):
        return self.target


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


def test_resolved_unc_swap_is_rejected_before_handle_reader(
    db_session_factory, settings, tmp_path, monkeypatch
):
    directory = tmp_path / "initially-local"
    directory.mkdir()
    (directory / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(service, "_temporary_roots", lambda: ())
    monkeypatch.setattr(service, "_system_roots", lambda: ())
    path_security = ResolveLocalToUnc()
    filesystem = RecordingFilesystem()

    with db_session_factory() as session:
        with pytest.raises(ManagerError) as caught:
            service.register_extension(
                session,
                settings,
                str(directory),
                filesystem=filesystem,
                path_security=path_security,
            )

    assert caught.value.code == "extension_path_forbidden"
    assert len(path_security.network_checks) == 2
    assert filesystem.called is False


def test_canonical_resolution_cannot_introduce_extension_delimiter(
    db_session_factory, settings, tmp_path, monkeypatch
):
    supplied = tmp_path / "initially-safe"
    supplied.mkdir()
    (supplied / "manifest.json").write_text("{}", encoding="utf-8")
    resolved = tmp_path / "resolved,ambiguous"
    path_security = ResolveToCommaPath(resolved)
    filesystem = RecordingFilesystem()
    monkeypatch.setattr(service, "_temporary_roots", lambda: ())
    monkeypatch.setattr(service, "_system_roots", lambda: ())

    with db_session_factory() as session:
        with pytest.raises(ManagerError) as caught:
            service.register_extension(
                session,
                settings,
                str(supplied),
                filesystem=filesystem,
                path_security=path_security,
            )

    assert caught.value.code == "extension_path_forbidden"
    assert filesystem.called is False


@pytest.mark.parametrize(
    "drive_type,expected",
    [
        (service.DRIVE_FIXED, False),
        (service.DRIVE_REMOTE, True),
    ],
)
def test_native_drive_detector_classifies_known_drive_types(drive_type, expected):
    roots = []
    detector = service.NativeNetworkPathDetector(
        windows=True,
        get_drive_type=lambda root: roots.append(root) or drive_type,
    )

    assert (
        detector.is_network("Z:\\extension", PureWindowsPath("Z:/extension"))
        is expected
    )
    assert roots == ["Z:\\"]


@pytest.mark.parametrize(
    "drive_type", [service.DRIVE_UNKNOWN, service.DRIVE_NO_ROOT_DIR, 99]
)
def test_native_drive_detector_fails_closed_for_indeterminate_drive(drive_type):
    detector = service.NativeNetworkPathDetector(
        windows=True, get_drive_type=lambda _root: drive_type
    )

    with pytest.raises(service.NetworkPathIndeterminate):
        detector.is_network("Z:\\extension", PureWindowsPath("Z:/extension"))


def test_native_drive_detector_rejects_unc_without_drive_api():
    detector = service.NativeNetworkPathDetector(
        windows=True,
        get_drive_type=lambda _root: (_ for _ in ()).throw(AssertionError()),
    )

    assert detector.is_network(
        r"\\server\share\extension", PureWindowsPath(r"\\server\share\extension")
    ) is True


@pytest.mark.parametrize("failure_errno", [errno.ELOOP, errno.ENOTDIR, errno.EACCES])
def test_posix_component_traversal_failures_are_unsafe(monkeypatch, failure_errno):
    calls = 0

    def fake_open(_path, _flags, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 10
        raise OSError(failure_errno, "private path detail")

    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_NOFOLLOW", 0x20000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_DIRECTORY", 0x10000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.open", fake_open
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.close", lambda _fd: None
    )
    approved = ApprovedDirectory(Path("/safe/extension"), device=1, inode=2)

    with pytest.raises(UnsafeManifestPath):
        SecureManifestFilesystem._read_posix(approved, 1024)


@pytest.mark.parametrize("failure_errno", [errno.ELOOP, errno.ENOTDIR])
def test_posix_manifest_nofollow_failures_are_unsafe(monkeypatch, failure_errno):
    calls = 0

    def fake_open(_path, _flags, **_kwargs):
        nonlocal calls
        calls += 1
        if calls <= len(ApprovedDirectory(Path("/safe/extension"), 1, 2).path.parts):
            return 10 + calls
        raise OSError(failure_errno, "private link detail")

    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_NOFOLLOW", 0x20000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_DIRECTORY", 0x10000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.open", fake_open
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.close", lambda _fd: None
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.fstat",
        lambda _fd: SimpleNamespace(st_dev=1, st_ino=2),
    )
    approved = ApprovedDirectory(Path("/safe/extension"), device=1, inode=2)

    with pytest.raises(UnsafeManifestPath):
        SecureManifestFilesystem._read_posix(approved, 1024)


def test_posix_missing_manifest_remains_manifest_read_failure(monkeypatch):
    calls = 0
    approved = ApprovedDirectory(Path("/safe/extension"), device=1, inode=2)

    def fake_open(_path, _flags, **_kwargs):
        nonlocal calls
        calls += 1
        if calls <= len(approved.path.parts):
            return 20 + calls
        raise OSError(errno.ENOENT, "private missing detail")

    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_NOFOLLOW", 0x20000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_DIRECTORY", 0x10000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.open", fake_open
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.close", lambda _fd: None
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.fstat",
        lambda _fd: SimpleNamespace(st_dev=1, st_ino=2),
    )

    with pytest.raises(ManifestReadFailure):
        SecureManifestFilesystem._read_posix(approved, 1024)


def test_posix_manifest_open_is_nonblocking(monkeypatch):
    approved = ApprovedDirectory(Path("/safe/extension"), device=1, inode=2)
    opens = []

    def fake_open(path, flags, **kwargs):
        opens.append((path, flags, kwargs))
        return 30 + len(opens)

    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_NOFOLLOW", 0x20000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_DIRECTORY", 0x10000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.O_NONBLOCK", 0x4000,
        raising=False,
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.open", fake_open
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.close", lambda _fd: None
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.fstat",
        lambda _fd: SimpleNamespace(
            st_dev=1,
            st_ino=2,
            st_mode=stat.S_IFREG if len(opens) == 4 else stat.S_IFDIR,
            st_size=0,
        ),
    )
    monkeypatch.setattr(
        "manager_backend.features.extensions.filesystem.os.read", lambda _fd, _size: b""
    )

    SecureManifestFilesystem._read_posix(approved, 1024)

    manifest_open = opens[-1]
    assert manifest_open[0] == "manifest.json"
    assert manifest_open[1] & 0x4000
