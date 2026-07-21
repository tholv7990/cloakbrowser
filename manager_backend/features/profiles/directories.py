from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from ...config import ManagerSettings
from ...errors import ManagerError


def _resolve_path(path: Path) -> Path:
    return path.resolve(strict=False)


def _canonical_profile_id(profile_id: object) -> str:
    if not isinstance(profile_id, str):
        raise ManagerError(
            "profile_directory_invalid",
            "The profile directory could not be resolved.",
            400,
        )
    try:
        canonical_id = str(UUID(profile_id))
    except (AttributeError, ValueError):
        raise ManagerError(
            "profile_directory_invalid",
            "The profile directory could not be resolved.",
            400,
        ) from None
    if profile_id != canonical_id:
        raise ManagerError(
            "profile_directory_invalid",
            "The profile directory could not be resolved.",
            400,
        )
    return canonical_id


def _ensure_contained(path: Path, root: Path) -> Path:
    try:
        resolved = _resolve_path(path)
        if not resolved.is_relative_to(root):
            raise ValueError("profile directory escapes the manager root")
        return resolved
    except (OSError, ValueError):
        raise ManagerError(
            "profile_directory_invalid",
            "The profile directory could not be resolved.",
            400,
        ) from None


def resolve_profile_directory(settings: ManagerSettings, profile_id: str) -> Path:
    """Return the canonical, manager-owned directory for a profile."""
    canonical_id = _canonical_profile_id(profile_id)
    try:
        data_root = _resolve_path(settings.data_root)
        profiles_root = _resolve_path(settings.profile_root)
    except OSError:
        raise ManagerError(
            "profile_directory_invalid",
            "The profile directory could not be resolved.",
            400,
        ) from None
    _ensure_contained(profiles_root, data_root)
    return _ensure_contained(profiles_root / canonical_id, profiles_root)


def open_profile_directory(
    path: Path, opener: Callable[[Path], Any] | None = None
) -> None:
    """Create and open a manager-owned directory with Windows Explorer."""
    if os.name != "nt":
        raise ManagerError(
            "directory_open_not_supported",
            "Opening profile directories is supported only on Windows.",
            501,
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
        open_with_explorer = opener if opener is not None else os.startfile
        open_with_explorer(path)
    except OSError:
        raise ManagerError(
            "directory_open_failed",
            "The profile directory could not be opened.",
            500,
        ) from None
