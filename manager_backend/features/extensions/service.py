from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ...config import ManagerSettings
from ...errors import ManagerError
from ...models import Extension, Profile
from .filesystem import (
    DEFAULT_MANIFEST_FILESYSTEM,
    ApprovedDirectory,
    ManifestFilesystem,
    ManifestReadFailure,
    ManifestTooLarge,
    UnsafeManifestPath,
)


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PERMISSIONS = 100
MAX_PERMISSION_LENGTH = 256
_PERMISSION_FIELDS = (
    "permissions",
    "optional_permissions",
    "host_permissions",
    "optional_host_permissions",
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6
_LOCAL_DRIVE_TYPES = frozenset(
    {DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_CDROM, DRIVE_RAMDISK}
)


class NetworkPathIndeterminate(Exception):
    """The operating system could not establish that a drive is local."""


class PathSecurityAdapter(Protocol):
    def is_network(self, supplied: str, path: Path) -> bool: ...

    def resolve(self, path: Path) -> Path: ...


class NativeNetworkPathDetector:
    def __init__(
        self,
        *,
        windows: bool | None = None,
        get_drive_type: Callable[[str], int] | None = None,
    ) -> None:
        self._windows = os.name == "nt" if windows is None else windows
        self._get_drive_type = get_drive_type or self._native_drive_type

    @staticmethod
    def _native_drive_type(root: str) -> int:
        try:
            return int(ctypes.windll.kernel32.GetDriveTypeW(root))
        except (AttributeError, OSError, ValueError, TypeError):
            raise NetworkPathIndeterminate from None

    def is_network(self, supplied: str, path: Path) -> bool:
        normalized = supplied.replace("/", "\\")
        path_text = str(path).replace("/", "\\")
        if normalized.startswith("\\\\") or path_text.startswith("\\\\"):
            return True
        if not self._windows:
            return False
        drive = path.drive
        if not drive:
            return False
        if str(drive).replace("/", "\\").startswith("\\\\"):
            return True
        try:
            drive_type = self._get_drive_type(f"{drive}\\")
        except NetworkPathIndeterminate:
            raise
        except Exception:
            raise NetworkPathIndeterminate from None
        if drive_type == DRIVE_REMOTE:
            return True
        if drive_type in _LOCAL_DRIVE_TYPES:
            return False
        raise NetworkPathIndeterminate


class NativePathSecurityAdapter:
    def __init__(self, detector: NativeNetworkPathDetector | None = None) -> None:
        self._detector = detector or NativeNetworkPathDetector()

    def is_network(self, supplied: str, path: Path) -> bool:
        return self._detector.is_network(supplied, path)

    def resolve(self, path: Path) -> Path:
        return path.resolve(strict=True)


DEFAULT_PATH_SECURITY = NativePathSecurityAdapter()


@dataclass(frozen=True, slots=True)
class ManifestMetadata:
    name: str
    version: str
    description: str
    manifest_version: int
    permissions: list[str]
    manifest_hash: str


def _path_error() -> ManagerError:
    return ManagerError(
        "extension_path_forbidden",
        "The extension directory is not an allowed local path.",
        422,
        {"directory": "forbidden"},
    )


def _manifest_error() -> ManagerError:
    return ManagerError(
        "extension_manifest_invalid",
        "The extension manifest is not a supported Manifest V2 or V3 document.",
        422,
        {"manifest": "invalid"},
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _temporary_roots() -> tuple[Path, ...]:
    values = [tempfile.gettempdir(), os.environ.get("TEMP"), os.environ.get("TMP")]
    return tuple(
        Path(value).resolve(strict=False)
        for value in dict.fromkeys(value for value in values if value)
    )


def _system_roots() -> tuple[Path, ...]:
    names = ("SYSTEMROOT", "WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA")
    return tuple(
        Path(value).resolve(strict=False)
        for value in dict.fromkeys(os.environ.get(name) for name in names)
        if value
    )


def _path_has_reparse_component(path: Path) -> bool:
    absolute = path.absolute()
    candidates = [absolute, *absolute.parents]
    for candidate in candidates:
        try:
            info = os.lstat(candidate)
        except OSError:
            continue
        attributes = getattr(info, "st_file_attributes", 0)
        if candidate.is_symlink() or attributes & _REPARSE_POINT:
            return True
    return False


def _canonical_directory(
    settings: ManagerSettings,
    supplied: str,
    path_security: PathSecurityAdapter = DEFAULT_PATH_SECURITY,
) -> ApprovedDirectory:
    if "\0" in supplied:
        raise _path_error()
    candidate = Path(supplied).expanduser()
    try:
        if path_security.is_network(supplied, candidate):
            raise _path_error()
        absolute = candidate.absolute()
        if _path_has_reparse_component(absolute):
            raise _path_error()
        resolved = path_security.resolve(absolute)
        if path_security.is_network(str(resolved), resolved):
            raise _path_error()
    except NetworkPathIndeterminate:
        raise _path_error() from None
    except (OSError, RuntimeError):
        raise ManagerError(
            "extension_directory_not_found",
            "The extension directory was not found.",
            422,
            {"directory": "not_found"},
        ) from None
    if not resolved.is_dir():
        raise ManagerError(
            "extension_directory_not_found",
            "The extension directory was not found.",
            422,
            {"directory": "not_directory"},
        )
    forbidden = (
        settings.profile_root.resolve(strict=False),
        *_temporary_roots(),
        *_system_roots(),
    )
    if any(_is_within(resolved, root) for root in forbidden):
        raise _path_error()
    try:
        identity = os.stat(resolved, follow_symlinks=False)
    except OSError:
        raise _path_error() from None
    if not stat.S_ISDIR(identity.st_mode) or _path_has_reparse_component(resolved):
        raise _path_error()
    return ApprovedDirectory(resolved, identity.st_dev, identity.st_ino)


def _load_json_object(raw: bytes) -> dict[str, Any]:
    def reject_constant(_value: str):
        raise ValueError("non-finite number")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise _manifest_error() from None
    if not isinstance(value, dict):
        raise _manifest_error()
    return value


def _bounded_text(value: Any, *, maximum: int, required: bool) -> str:
    if not isinstance(value, str):
        raise _manifest_error()
    normalized = unicodedata.normalize("NFKC", " ".join(value.split()))
    if required and not normalized:
        raise _manifest_error()
    if len(normalized) > maximum:
        if required:
            raise _manifest_error()
        return normalized[:maximum]
    return normalized


def _permission_summary(manifest: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for field in _PERMISSION_FIELDS:
        raw = manifest.get(field, [])
        if not isinstance(raw, list):
            raise _manifest_error()
        for item in raw:
            if not isinstance(item, str) or not item or len(item) > MAX_PERMISSION_LENGTH:
                raise _manifest_error()
            values.add(item)
    return sorted(values)[:MAX_PERMISSIONS]


def _manifest_metadata(raw: bytes) -> ManifestMetadata:
    manifest = _load_json_object(raw)
    manifest_version = manifest.get("manifest_version")
    if type(manifest_version) is not int or manifest_version not in (2, 3):
        raise _manifest_error()
    name = _bounded_text(manifest.get("name"), maximum=160, required=True)
    version = _bounded_text(manifest.get("version"), maximum=64, required=True)
    description_value = manifest.get("description", "")
    description = _bounded_text(description_value, maximum=500, required=False)
    try:
        canonical = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _manifest_error() from None
    return ManifestMetadata(
        name=name,
        version=version,
        description=description,
        manifest_version=manifest_version,
        permissions=_permission_summary(manifest),
        manifest_hash=hashlib.sha256(canonical).hexdigest(),
    )


def _read_manifest_metadata(
    settings: ManagerSettings,
    supplied: str,
    filesystem: ManifestFilesystem,
    path_security: PathSecurityAdapter,
) -> tuple[Path, ManifestMetadata]:
    approved = _canonical_directory(settings, supplied, path_security)
    try:
        raw = filesystem.read_manifest(approved, MAX_MANIFEST_BYTES)
    except UnsafeManifestPath:
        raise _path_error() from None
    except ManifestTooLarge:
        raise ManagerError(
            "extension_manifest_too_large",
            "The extension manifest exceeds the 1 MiB limit.",
            413,
            {"manifest": "too_large"},
        ) from None
    except ManifestReadFailure:
        raise _manifest_error() from None
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManagerError(
            "extension_manifest_too_large",
            "The extension manifest exceeds the 1 MiB limit.",
            413,
            {"manifest": "too_large"},
        )
    return approved.path, _manifest_metadata(raw)


def _apply_metadata(extension: Extension, metadata: ManifestMetadata) -> None:
    extension.name = metadata.name
    extension.version = metadata.version
    extension.description = metadata.description
    extension.manifest_version = metadata.manifest_version
    extension.permissions = metadata.permissions
    extension.manifest_hash = metadata.manifest_hash


def get_extension(session: Session, extension_id: str) -> Extension:
    extension = session.get(Extension, extension_id)
    if extension is None:
        raise ManagerError(
            "extension_not_found", "The requested extension was not found.", 404
        )
    return extension


def list_extensions(session: Session) -> list[Extension]:
    return list(session.scalars(select(Extension).order_by(Extension.name, Extension.id)))


def validate_registered_extension_path(
    settings: ManagerSettings,
    extension: Extension,
    *,
    filesystem: ManifestFilesystem = DEFAULT_MANIFEST_FILESYSTEM,
    path_security: PathSecurityAdapter = DEFAULT_PATH_SECURITY,
) -> str:
    """Revalidate one registered extension immediately before browser launch."""

    directory, metadata = _read_manifest_metadata(
        settings, extension.directory, filesystem, path_security
    )
    if directory != Path(extension.directory):
        raise _path_error()
    if metadata.manifest_hash != extension.manifest_hash:
        raise ManagerError(
            "extension_manifest_changed",
            "A registered extension changed; refresh it before launching.",
            409,
        )
    return str(directory)


def register_extension(
    session: Session,
    settings: ManagerSettings,
    supplied: str,
    *,
    filesystem: ManifestFilesystem = DEFAULT_MANIFEST_FILESYSTEM,
    path_security: PathSecurityAdapter = DEFAULT_PATH_SECURITY,
) -> tuple[Extension, bool]:
    directory, metadata = _read_manifest_metadata(
        settings, supplied, filesystem, path_security
    )
    normalized = str(directory)
    existing = session.scalar(select(Extension).where(Extension.directory == normalized))
    if existing is not None:
        if existing.manifest_hash != metadata.manifest_hash:
            raise ManagerError(
                "extension_manifest_changed",
                "The registered manifest changed; refresh the extension metadata.",
                409,
            )
        return existing, False
    extension = Extension(directory=normalized)
    _apply_metadata(extension, metadata)
    session.add(extension)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Extension).where(Extension.directory == normalized))
        if existing is not None and existing.manifest_hash == metadata.manifest_hash:
            return existing, False
        raise ManagerError(
            "extension_manifest_changed",
            "The extension directory is already registered with different metadata.",
            409,
        ) from None
    session.refresh(extension)
    return extension, True


def update_extension(
    session: Session,
    settings: ManagerSettings,
    extension_id: str,
    *,
    enabled: bool | None,
    refresh: bool,
    filesystem: ManifestFilesystem = DEFAULT_MANIFEST_FILESYSTEM,
    path_security: PathSecurityAdapter = DEFAULT_PATH_SECURITY,
) -> Extension:
    extension = get_extension(session, extension_id)
    if refresh:
        _directory, metadata = _read_manifest_metadata(
            settings, extension.directory, filesystem, path_security
        )
        _apply_metadata(extension, metadata)
    if enabled is not None:
        extension.enabled = enabled
    session.commit()
    session.refresh(extension)
    return extension


def unregister_extension(session: Session, extension_id: str) -> None:
    extension = get_extension(session, extension_id)
    session.delete(extension)
    session.commit()


def _reserve_assignment_transaction(session: Session) -> None:
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def set_profile_extensions(
    session: Session, profile_id: str, ids: list[str]
) -> list[Extension]:
    try:
        _reserve_assignment_transaction(session)
        profile = session.get(Profile, profile_id)
        if profile is None or profile.deleted_at is not None:
            raise ManagerError(
                "profile_not_found", "The requested profile was not found.", 404
            )
        extensions = (
            list(session.scalars(select(Extension).where(Extension.id.in_(ids))))
            if ids
            else []
        )
        if len(extensions) != len(ids):
            raise ManagerError(
                "invalid_extension_reference",
                "One or more extension references do not exist.",
                422,
                {"extension_ids": "contains_unknown_id"},
            )
        by_id = {extension.id: extension for extension in extensions}
        ordered = [by_id[extension_id] for extension_id in ids]
        profile.extensions = ordered
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ManagerError(
            "invalid_extension_reference",
            "One or more extension references changed during assignment.",
            422,
            {"extension_ids": "changed_during_update"},
        ) from None
    except OperationalError:
        session.rollback()
        raise ManagerError(
            "extension_assignment_conflict",
            "The profile extension assignment changed concurrently. Try again.",
            409,
        ) from None
    except Exception:
        session.rollback()
        raise
    return ordered


def extension_to_dict(extension: Extension) -> dict[str, Any]:
    return {
        "id": extension.id,
        "directory": extension.directory,
        "name": extension.name,
        "version": extension.version,
        "description": extension.description,
        "manifest_version": extension.manifest_version,
        "permissions": extension.permissions,
        "enabled": extension.enabled,
        "manifest_hash": extension.manifest_hash,
        "created_at": extension.created_at,
        "updated_at": extension.updated_at,
    }
