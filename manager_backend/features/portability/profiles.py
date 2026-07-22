from __future__ import annotations

import unicodedata
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from ...config import ManagerSettings
from ...errors import ManagerError
from ...fingerprints import build_fingerprint_identity, generate_unique_seed
from ...models import Folder, Profile, Tag, WorkflowStatus, utc_now
from ..profiles.directories import resolve_profile_directory
from .schemas import (
    PortableBehaviorSettings,
    PortableColoredCatalog,
    PortableExtension,
    PortableFolder,
    PortableProfile,
    PortableProxy,
    MAX_PORTABLE_PERMISSIONS,
    MAX_PORTABLE_PERMISSION_KEY_LENGTH,
    PROFILE_EXPORT_FORMAT,
    PROFILE_EXPORT_VERSION,
    ProfileExportV1,
    ProfileImportResult,
    ProfileImportWarning,
)


_PORTABLE_BEHAVIOR_FIELDS = tuple(PortableBehaviorSettings.model_fields)


def _canonical_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_export_profile(session: Session, profile_id: str) -> Profile:
    profile = session.scalar(
        select(Profile)
        .options(
            selectinload(Profile.folder),
            selectinload(Profile.workflow_status),
            selectinload(Profile.tags),
            selectinload(Profile.proxy),
        )
        .where(Profile.id == profile_id)
    )
    if profile is None:
        raise ManagerError("profile_not_found", "The requested profile was not found.", 404)
    return profile


def _portable_behavior(value: dict[str, Any]) -> PortableBehaviorSettings:
    safe = {key: value[key] for key in _PORTABLE_BEHAVIOR_FIELDS if key in value}
    if "permissions" in safe:
        permissions = safe["permissions"]
        keys = sorted(
            key
            for key, setting in permissions.items()
            if isinstance(key, str)
            and 0 < len(key) <= MAX_PORTABLE_PERMISSION_KEY_LENGTH
            and setting in {"ask", "allow", "block"}
        )[:MAX_PORTABLE_PERMISSIONS]
        safe["permissions"] = {key: permissions[key] for key in keys}
    return PortableBehaviorSettings.model_validate(safe)


def export_profile(
    session: Session,
    profile_id: str,
    *,
    exported_at: datetime | None = None,
    warning_codes: list[str] | None = None,
) -> ProfileExportV1:
    source = _load_export_profile(session, profile_id)
    tags = sorted(
        (PortableColoredCatalog(name=tag.name, color=tag.color) for tag in source.tags),
        key=lambda item: (_normalized_name(item.name), item.name, item.color),
    )
    startup_urls, skipped_extension_urls = _portable_startup_urls(source.startup_urls)
    if skipped_extension_urls and warning_codes is not None:
        warning_codes.append("chrome_extension_startup_urls_skipped")
    proxy = None
    if source.proxy is not None:
        proxy = PortableProxy(
            scheme=source.proxy.scheme,
            host=source.proxy.host,
            port=source.proxy.port,
        )
    document = ProfileExportV1(
        format=PROFILE_EXPORT_FORMAT,
        version=PROFILE_EXPORT_VERSION,
        exported_at=_canonical_utc(exported_at or utc_now()),
        profile=PortableProfile(
            name=source.name,
            folder=(PortableFolder(name=source.folder.name) if source.folder else None),
            workflow_status=(
                PortableColoredCatalog(
                    name=source.workflow_status.name,
                    color=source.workflow_status.color,
                )
                if source.workflow_status
                else None
            ),
            tags=tags,
            notes=source.notes,
            pinned=source.pinned,
            startup_urls=startup_urls,
            fingerprint_preset=source.fingerprint_preset,
            browser_version_mode=source.browser_version_mode,
            browser_version=source.browser_version,
            user_agent_mode=source.user_agent_mode,
            custom_user_agent=source.custom_user_agent,
            location=source.location,
            window=source.window,
            behavior=_portable_behavior(source.behavior),
            proxy=proxy,
            test_proxy_before_launch=source.test_proxy_before_launch,
        ),
        extensions=_export_extensions(source),
    )
    return document


def _export_extensions(_source: Profile) -> list[PortableExtension]:
    # Extension persistence is introduced by the extension-management task. Keeping
    # this seam here makes v1 documents stable before and after that model exists.
    return []


def _normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()


def _portable_startup_urls(values: list[str]) -> tuple[list[str], int]:
    portable = [
        value for value in values if urlsplit(value).scheme.lower() != "chrome-extension"
    ]
    return portable, len(values) - len(portable)


def _is_retryable_sqlite_lock(error: OperationalError) -> bool:
    code = getattr(error.orig, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    return str(error.orig).strip().lower() in {
        "database is locked",
        "database table is locked",
    }


@dataclass(slots=True)
class _ImportIndex:
    folders: dict[str, Folder]
    statuses: dict[str, WorkflowStatus]
    tags: dict[str, Tag]
    profile_names: set[str]
    next_folder_position: int
    next_status_position: int


def _catalog_index(items):
    indexed = {}
    for item in sorted(
        items,
        key=lambda entry: (_normalized_name(entry.name), entry.name, entry.id),
    ):
        indexed.setdefault(_normalized_name(item.name), item)
    return indexed


def _load_import_index(session: Session) -> _ImportIndex:
    folders = list(session.scalars(select(Folder)))
    statuses = list(session.scalars(select(WorkflowStatus)))
    tags = list(session.scalars(select(Tag)))
    return _ImportIndex(
        folders=_catalog_index(folders),
        statuses=_catalog_index(statuses),
        tags=_catalog_index(tags),
        profile_names={_normalized_name(name) for name in session.scalars(select(Profile.name))},
        next_folder_position=max((item.position for item in folders), default=-1) + 1,
        next_status_position=max((item.position for item in statuses), default=-1) + 1,
    )


def _resolve_folder(
    session: Session, index: _ImportIndex, value: PortableFolder | None
) -> Folder | None:
    if value is None:
        return None
    normalized = _normalized_name(value.name)
    existing = index.folders.get(normalized)
    if existing is not None:
        return existing
    item = Folder(name=value.name, position=index.next_folder_position)
    index.next_folder_position += 1
    index.folders[normalized] = item
    session.add(item)
    return item


def _resolve_colored_catalog(
    session: Session,
    index: _ImportIndex,
    model: type[Tag] | type[WorkflowStatus],
    value: PortableColoredCatalog | None,
):
    if value is None:
        return None
    normalized = _normalized_name(value.name)
    catalog = index.statuses if model is WorkflowStatus else index.tags
    existing = catalog.get(normalized)
    if existing is not None:
        return existing
    values: dict[str, Any] = {"name": value.name, "color": value.color}
    if model is WorkflowStatus:
        values["position"] = index.next_status_position
        index.next_status_position += 1
    item = model(**values)
    catalog[normalized] = item
    session.add(item)
    return item


def _resolve_tags(
    session: Session, index: _ImportIndex, values: list[PortableColoredCatalog]
) -> list[Tag]:
    resolved: list[Tag] = []
    seen: set[str] = set()
    ordered = sorted(
        values,
        key=lambda item: (_normalized_name(item.name), item.name, item.color),
    )
    for value in ordered:
        normalized = _normalized_name(value.name)
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(_resolve_colored_catalog(session, index, Tag, value))
    return resolved


def _collision_safe_name(index: _ImportIndex, requested: str) -> str:
    taken = index.profile_names
    if _normalized_name(requested) not in taken:
        return requested
    number = 1
    while True:
        suffix = f" (imported {number})"
        candidate = f"{requested[: 80 - len(suffix)]}{suffix}"
        if _normalized_name(candidate) not in taken:
            return candidate
        number += 1


def _new_seed(session: Session) -> str:
    def is_taken(seed: str) -> bool:
        return bool(session.scalar(select(func.count(Profile.id)).where(Profile.fingerprint_seed == seed)))

    return generate_unique_seed(is_taken)


def _reserve_import_transaction(session: Session) -> None:
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _create_profile_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)


def _remove_empty_profile_directory(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.rmdir()
    except OSError:
        pass


def _warnings(document: ProfileExportV1) -> list[ProfileImportWarning]:
    warnings: list[ProfileImportWarning] = []
    if document.profile.proxy is not None:
        warnings.append(
            ProfileImportWarning(
                code="proxy_assignment_skipped",
                message="Proxy metadata was preserved for review, but no proxy was assigned.",
            )
        )
    warnings.extend(
        ProfileImportWarning(
            code="extension_missing",
            message=(
                f"Extension reference {index + 1} was not assigned because no matching "
                "local extension is registered."
            ),
        )
        for index, _extension in enumerate(document.extensions)
    )
    _urls, skipped_extension_urls = _portable_startup_urls(
        document.profile.startup_urls
    )
    if skipped_extension_urls:
        warnings.append(
            ProfileImportWarning(
                code="chrome_extension_startup_url_skipped",
                message=(
                    "Machine-specific extension startup URLs were not imported; "
                    "assign extensions by manifest metadata instead."
                ),
            )
        )
    return warnings


def import_profile(
    session: Session,
    settings: ManagerSettings,
    document: ProfileExportV1,
) -> ProfileImportResult:
    profile_directory: Path | None = None
    directory_created = False
    try:
        _reserve_import_transaction(session)
        index = _load_import_index(session)
        portable = document.profile
        folder = _resolve_folder(session, index, portable.folder)
        workflow_status = _resolve_colored_catalog(
            session, index, WorkflowStatus, portable.workflow_status
        )
        tags = _resolve_tags(session, index, portable.tags)
        seed = _new_seed(session)
        startup_urls, _skipped_extension_urls = _portable_startup_urls(
            portable.startup_urls
        )
        behavior = {
            **portable.behavior.model_dump(mode="json"),
            "download_directory_mode": "profile",
            "custom_download_directory": None,
            "additional_args": [],
        }
        identity = build_fingerprint_identity(
            seed=seed,
            fingerprint_preset=portable.fingerprint_preset,
            browser_version_mode=portable.browser_version_mode,
            browser_version=portable.browser_version,
            user_agent_mode=portable.user_agent_mode,
            custom_user_agent=portable.custom_user_agent,
            location=portable.location,
            window=portable.window,
            behavior=behavior,
        )
        profile = Profile(
            id=str(uuid4()),
            name=_collision_safe_name(index, portable.name),
            folder=folder,
            workflow_status=workflow_status,
            tags=tags,
            notes=portable.notes,
            pinned=portable.pinned,
            startup_urls=startup_urls,
            fingerprint_seed=identity.seed,
            fingerprint_preset=portable.fingerprint_preset,
            fingerprint_revision=identity.revision,
            fingerprint_config_hash=identity.config_hash,
            browser_version_mode=portable.browser_version_mode,
            browser_version=portable.browser_version,
            user_agent_mode=portable.user_agent_mode,
            custom_user_agent=portable.custom_user_agent,
            location=portable.location.model_dump(mode="json"),
            window=portable.window.model_dump(mode="json"),
            behavior=behavior,
            proxy_id=None,
            test_proxy_before_launch=portable.test_proxy_before_launch,
        )
        session.add(profile)
        session.flush()
        profile_directory = resolve_profile_directory(settings, profile.id)
        _create_profile_directory(profile_directory)
        directory_created = True
        session.commit()
    except OperationalError as error:
        session.rollback()
        if directory_created:
            _remove_empty_profile_directory(profile_directory)
        if _is_retryable_sqlite_lock(error):
            raise ManagerError(
                "profile_import_busy",
                "The profile import could not acquire the database write lock. Try again.",
                409,
            ) from None
        raise ManagerError(
            "profile_import_failed",
            "The profile document could not be imported.",
            500,
        ) from None
    except (IntegrityError, OSError) as error:
        session.rollback()
        if directory_created:
            _remove_empty_profile_directory(profile_directory)
        raise ManagerError(
            "profile_import_failed",
            "The profile document could not be imported.",
            409 if isinstance(error, IntegrityError) else 500,
        ) from None
    except Exception:
        session.rollback()
        if directory_created:
            _remove_empty_profile_directory(profile_directory)
        raise

    return ProfileImportResult(
        profile_id=profile.id,
        profile_name=profile.name,
        warnings=_warnings(document),
    )
