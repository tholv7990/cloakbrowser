from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID


class ArtifactBoundaryError(Exception):
    """An artifact path or payload crossed the manager-owned boundary."""


class ArtifactNotFound(Exception):
    """The persisted artifact is absent."""


class ArtifactUnavailable(Exception):
    """The persisted artifact cannot be served safely."""


@dataclass(frozen=True, slots=True)
class DiagnosticArtifactPaths:
    report_path: str
    screenshot_path: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticArtifact:
    content: bytes
    media_type: str
    filename: str
    disposition: str


_ARTIFACT_KINDS = {
    "report": ("report.json", "application/json", "attachment"),
    "screenshot": ("screenshot.png", "image/png", "inline"),
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(slots=True)
class _BoundaryHandle:
    path: Path
    identity: tuple[int, ...]
    final_path: str
    descriptor: int | None = None
    native_handle: int | None = None

    def close(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
        if self.native_handle is not None:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            close_handle(wintypes.HANDLE(self.native_handle))
            self.native_handle = None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_run_id(run_id: str) -> str:
    try:
        parsed = UUID(run_id)
    except (AttributeError, TypeError, ValueError):
        raise ArtifactBoundaryError from None
    normalized = str(parsed)
    if run_id != normalized:
        raise ArtifactBoundaryError
    return normalized


def diagnostic_run_root(data_root: Path, run_id: str) -> Path:
    """Create and return the exact canonical directory owned by one run."""

    normalized = _validated_run_id(run_id)
    try:
        canonical_data_root = Path(data_root).resolve(strict=False)
        canonical_data_root.mkdir(parents=True, exist_ok=True)
        diagnostics_root = (canonical_data_root / "diagnostics").resolve(strict=False)
        if not _is_within(diagnostics_root, canonical_data_root):
            raise ArtifactBoundaryError
        diagnostics_root.mkdir(parents=True, exist_ok=True)
        diagnostics_root = diagnostics_root.resolve(strict=True)
        if not _is_within(diagnostics_root, canonical_data_root):
            raise ArtifactBoundaryError

        lexical_run_root = diagnostics_root / normalized
        resolved_before_create = lexical_run_root.resolve(strict=False)
        if resolved_before_create != lexical_run_root or not _is_within(
            resolved_before_create, diagnostics_root
        ):
            raise ArtifactBoundaryError
        lexical_run_root.mkdir(mode=0o700, exist_ok=True)
        canonical_run_root = lexical_run_root.resolve(strict=True)
        if canonical_run_root != lexical_run_root or not _is_within(
            canonical_run_root, diagnostics_root
        ):
            raise ArtifactBoundaryError
        return canonical_run_root
    except ArtifactBoundaryError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ArtifactBoundaryError from None


def _owned_file(run_root: Path, name: str) -> Path:
    candidate = run_root / name
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        raise ArtifactBoundaryError from None
    if resolved.parent != run_root or not _is_within(resolved, run_root):
        raise ArtifactBoundaryError
    return candidate


def artifact_url_if_owned(
    value: str | None, data_root: Path, run_id: str, kind: str
) -> str | None:
    """Return only a route identifier; never expose a persisted local path."""

    if value is None or kind not in _ARTIFACT_KINDS:
        return None
    try:
        normalized = _validated_run_id(run_id)
        filename = _ARTIFACT_KINDS[kind][0]
        expected = Path(data_root).resolve() / "diagnostics" / normalized / filename
        supplied = Path(value)
        if not supplied.is_absolute() or supplied.absolute() != expected:
            return None
    except (ArtifactBoundaryError, OSError, RuntimeError, ValueError):
        return None
    return f"/api/v1/diagnostics/{normalized}/artifacts/{kind}"


def _is_link_or_reparse(path: Path) -> bool:
    info = os.lstat(path)
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _normalized_final_path(value: str | Path) -> str:
    raw = str(value)
    if raw.startswith("\\\\?\\UNC\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return os.path.normcase(os.path.abspath(raw))


def _open_windows_boundary(path: Path) -> _BoundaryHandle:
    import ctypes
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_final_path.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x80,  # FILE_READ_ATTRIBUTES
        0x1 | 0x2 | 0x4,  # FILE_SHARE_READ | WRITE | DELETE
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed", str(path))
    try:
        information = ByHandleFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle failed")
        if information.file_attributes & _REPARSE_POINT:
            raise ArtifactUnavailable
        buffer = ctypes.create_unicode_buffer(32_768)
        length = get_final_path(handle, buffer, len(buffer), 0)
        if length == 0 or length >= len(buffer):
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        return _BoundaryHandle(
            path=path,
            identity=(
                int(information.volume_serial_number),
                int(information.file_index_high),
                int(information.file_index_low),
            ),
            final_path=_normalized_final_path(buffer.value),
            native_handle=int(handle),
        )
    except Exception:
        close_handle(handle)
        raise


def _open_posix_boundary(path: Path) -> _BoundaryHandle:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        information = os.fstat(descriptor)
        if not stat.S_ISDIR(information.st_mode):
            raise ArtifactUnavailable
        return _BoundaryHandle(
            path=path,
            identity=(int(information.st_dev), int(information.st_ino)),
            final_path=_normalized_final_path(path.resolve(strict=True)),
            descriptor=descriptor,
        )
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _held_boundary(path: Path) -> Iterator[_BoundaryHandle]:
    boundary = (
        _open_windows_boundary(path) if os.name == "nt" else _open_posix_boundary(path)
    )
    try:
        yield boundary
    finally:
        boundary.close()


def _boundary_is_current(boundary: _BoundaryHandle) -> bool:
    try:
        with _held_boundary(boundary.path) as current:
            return (
                current.identity == boundary.identity
                and current.final_path == boundary.final_path
            )
    except (ArtifactUnavailable, OSError, RuntimeError, ValueError):
        return False


def _require_current_boundaries(boundaries: tuple[_BoundaryHandle, ...]) -> None:
    if not all(_boundary_is_current(boundary) for boundary in boundaries):
        raise ArtifactUnavailable


def read_diagnostic_artifact(
    data_root: Path,
    run_id: str,
    kind: str,
    persisted_path: str | None,
    *,
    max_bytes: int,
) -> DiagnosticArtifact:
    """Read an exact bounded run artifact through a verified regular-file handle."""

    if kind not in _ARTIFACT_KINDS or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ArtifactUnavailable
    if persisted_path is None:
        raise ArtifactNotFound
    try:
        normalized = _validated_run_id(run_id)
        filename, media_type, disposition = _ARTIFACT_KINDS[kind]
        canonical_data_root = Path(data_root).resolve(strict=True)
        diagnostics_root = canonical_data_root / "diagnostics"
        run_root = diagnostics_root / normalized
        candidate = run_root / filename
        supplied = Path(persisted_path)
        if not supplied.is_absolute() or supplied.absolute() != candidate:
            raise ArtifactUnavailable
        with ExitStack() as stack:
            boundaries = tuple(
                stack.enter_context(_held_boundary(boundary))
                for boundary in (diagnostics_root, run_root)
            )
            for boundary in (diagnostics_root, run_root):
                if (
                    _is_link_or_reparse(boundary)
                    or boundary.resolve(strict=True) != boundary
                ):
                    raise ArtifactUnavailable
            _require_current_boundaries(boundaries)
            before = os.lstat(candidate)
            if (
                not stat.S_ISREG(before.st_mode)
                or _is_link_or_reparse(candidate)
                or before.st_size > max_bytes
            ):
                raise ArtifactUnavailable
            flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(candidate, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino)
                    != (before.st_dev, before.st_ino)
                    or opened.st_size > max_bytes
                ):
                    raise ArtifactUnavailable
                _require_current_boundaries(boundaries)
                chunks: list[bytes] = []
                remaining = max_bytes + 1
                while remaining > 0:
                    chunk = os.read(descriptor, min(64 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b"".join(chunks)
                if len(content) > max_bytes or len(content) != opened.st_size:
                    raise ArtifactUnavailable
                after = os.lstat(candidate)
                if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                    raise ArtifactUnavailable
                _require_current_boundaries(boundaries)
            finally:
                os.close(descriptor)
    except ArtifactNotFound:
        raise
    except ArtifactUnavailable:
        raise
    except FileNotFoundError:
        raise ArtifactNotFound from None
    except (ArtifactBoundaryError, OSError, RuntimeError, ValueError):
        raise ArtifactUnavailable from None
    return DiagnosticArtifact(
        content=content,
        media_type=media_type,
        filename=f"diagnostic-{normalized}-{filename}",
        disposition=disposition,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
    except OSError:
        raise ArtifactBoundaryError from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def write_diagnostic_artifacts(
    data_root: Path,
    run_id: str,
    *,
    report: dict[str, Any],
    screenshot: bytes | None,
    max_report_bytes: int = 1024 * 1024,
    max_screenshot_bytes: int = 10 * 1024 * 1024,
) -> DiagnosticArtifactPaths:
    """Atomically persist bounded artifacts below one exact diagnostic root."""

    if not isinstance(report, dict) or not isinstance(max_report_bytes, int):
        raise ArtifactBoundaryError
    if screenshot is not None and not isinstance(screenshot, bytes):
        raise ArtifactBoundaryError
    try:
        report_payload = json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ArtifactBoundaryError from None
    if len(report_payload) > max_report_bytes:
        raise ArtifactBoundaryError
    if screenshot is not None and len(screenshot) > max_screenshot_bytes:
        raise ArtifactBoundaryError

    run_root = diagnostic_run_root(data_root, run_id)
    report_path = _owned_file(run_root, "report.json")
    screenshot_path = (
        _owned_file(run_root, "screenshot.png") if screenshot is not None else None
    )
    _atomic_write(report_path, report_payload)
    if screenshot_path is not None:
        _atomic_write(screenshot_path, screenshot)
    return DiagnosticArtifactPaths(
        report_path=str(report_path),
        screenshot_path=str(screenshot_path) if screenshot_path is not None else None,
    )
