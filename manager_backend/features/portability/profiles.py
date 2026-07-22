from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
        safe["permissions"] = {key: permissions[key] for key in sorted(permissions)}
    return PortableBehaviorSettings.model_validate(safe)


def export_profile(
    session: Session,
    profile_id: str,
    *,
    exported_at: datetime | None = None,
) -> ProfileExportV1:
    source = _load_export_profile(session, profile_id)
    tags = sorted(
        (PortableColoredCatalog(name=tag.name, color=tag.color) for tag in source.tags),
        key=lambda item: (item.name.casefold(), item.color),
    )
    proxy = None
    if source.proxy is not None:
        proxy = PortableProxy(
            scheme=source.proxy.scheme,
            host=source.proxy.host,
            port=source.proxy.port,
        )
    document = ProfileExportV1(
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
            startup_urls=list(source.startup_urls),
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
    return " ".join(value.split()).casefold()


def _next_position(session: Session, model: type[Folder] | type[WorkflowStatus]) -> int:
    current = session.scalar(select(func.max(model.position)))
    return 0 if current is None else int(current) + 1


def _find_catalog(session: Session, model, name: str):
    wanted = _normalized_name(name)
    return next(
        (item for item in session.scalars(select(model)) if _normalized_name(item.name) == wanted),
        None,
    )


def _resolve_folder(session: Session, value: PortableFolder | None) -> Folder | None:
    if value is None:
        return None
    existing = _find_catalog(session, Folder, value.name)
    if existing is not None:
        return existing
    item = Folder(name=value.name, position=_next_position(session, Folder))
    session.add(item)
    return item


def _resolve_colored_catalog(
    session: Session,
    model: type[Tag] | type[WorkflowStatus],
    value: PortableColoredCatalog | None,
):
    if value is None:
        return None
    existing = _find_catalog(session, model, value.name)
    if existing is not None:
        return existing
    values: dict[str, Any] = {"name": value.name, "color": value.color}
    if model is WorkflowStatus:
        values["position"] = _next_position(session, WorkflowStatus)
    item = model(**values)
    session.add(item)
    return item


def _resolve_tags(session: Session, values: list[PortableColoredCatalog]) -> list[Tag]:
    resolved: list[Tag] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalized_name(value.name)
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(_resolve_colored_catalog(session, Tag, value))
    return resolved


def _collision_safe_name(session: Session, requested: str) -> str:
    taken = {_normalized_name(name) for name in session.scalars(select(Profile.name))}
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
    return warnings


def import_profile(
    session: Session,
    document: ProfileExportV1,
    *,
    settings: ManagerSettings | None = None,
) -> ProfileImportResult:
    profile_directory: Path | None = None
    directory_created = False
    try:
        portable = document.profile
        folder = _resolve_folder(session, portable.folder)
        workflow_status = _resolve_colored_catalog(
            session, WorkflowStatus, portable.workflow_status
        )
        tags = _resolve_tags(session, portable.tags)
        seed = _new_seed(session)
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
            name=_collision_safe_name(session, portable.name),
            folder=folder,
            workflow_status=workflow_status,
            tags=tags,
            notes=portable.notes,
            pinned=portable.pinned,
            startup_urls=list(portable.startup_urls),
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
        if settings is not None:
            profile_directory = resolve_profile_directory(settings, profile.id)
            _create_profile_directory(profile_directory)
            directory_created = True
        session.commit()
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
