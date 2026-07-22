from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID


class ArtifactBoundaryError(Exception):
    """An artifact path or payload crossed the manager-owned boundary."""


@dataclass(frozen=True, slots=True)
class DiagnosticArtifactPaths:
    report_path: str
    screenshot_path: str | None


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
