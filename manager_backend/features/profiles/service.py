from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ...config import ManagerSettings
from ...errors import ManagerError
from ...fingerprints import build_fingerprint_identity, generate_unique_seed
from ...models import Folder, Profile, Proxy, Tag, WorkflowStatus, utc_now
from .directories import resolve_profile_directory
from .schemas import BulkProfileRequest, ProfileCreate, ProfilePatch, ProfileRead


_FINGERPRINT_FIELDS = {
    "fingerprint_preset",
    "browser_version_mode",
    "browser_version",
    "user_agent_mode",
    "custom_user_agent",
    "location",
    "window",
    "behavior",
}
_SORT_FIELDS = {
    "name": Profile.name,
    "created_at": Profile.created_at,
    "updated_at": Profile.updated_at,
    "last_opened_at": Profile.last_opened_at,
}


def _seed_is_taken(session: Session, seed: str) -> bool:
    return session.scalar(
        select(func.count(Profile.id)).where(Profile.fingerprint_seed == seed)
    ) > 0


def _new_seed(session: Session) -> str:
    return generate_unique_seed(lambda seed: _seed_is_taken(session, seed))


def _validate_references(
    session: Session,
    *,
    folder_id: str | None,
    status_id: str | None,
    tag_ids: list[str],
    proxy_id: str | None,
) -> list[Tag]:
    errors: dict[str, str] = {}
    if folder_id is not None and session.get(Folder, folder_id) is None:
        errors["folder_id"] = "not_found"
    if status_id is not None and session.get(WorkflowStatus, status_id) is None:
        errors["workflow_status_id"] = "not_found"
    if proxy_id is not None:
        proxy = session.get(Proxy, proxy_id)
        if proxy is None or proxy.deleted_at is not None:
            errors["proxy_id"] = "not_found"
    unique_tag_ids = list(dict.fromkeys(tag_ids))
    tags = (
        list(session.scalars(select(Tag).where(Tag.id.in_(unique_tag_ids))))
        if unique_tag_ids
        else []
    )
    if len(tags) != len(unique_tag_ids):
        errors["tag_ids"] = "contains_unknown_id"
    if errors:
        raise ManagerError(
            "invalid_profile_reference",
            "One or more profile references do not exist.",
            422,
            errors,
        )
    by_id = {tag.id: tag for tag in tags}
    return [by_id[tag_id] for tag_id in unique_tag_ids]


def _fingerprint_identity(seed: str, values: dict[str, Any]):
    return build_fingerprint_identity(
        seed=seed,
        fingerprint_preset=values["fingerprint_preset"],
        browser_version_mode=values["browser_version_mode"],
        browser_version=values.get("browser_version"),
        user_agent_mode=values["user_agent_mode"],
        custom_user_agent=values.get("custom_user_agent"),
        location=values["location"],
        window=values["window"],
        behavior=values["behavior"],
    )


def _profile_values(payload: ProfileCreate) -> tuple[dict[str, Any], list[str]]:
    values = payload.model_dump()
    tag_ids = values.pop("tag_ids")
    values["status_id"] = values.pop("workflow_status_id")
    values["location"] = payload.location.model_dump(mode="json")
    values["window"] = payload.window.model_dump(mode="json")
    values["behavior"] = payload.behavior.model_dump(mode="json")
    return values, tag_ids


def create_profile(session: Session, payload: ProfileCreate) -> Profile:
    values, tag_ids = _profile_values(payload)
    supplied_seed = values.pop("fingerprint_seed")
    if supplied_seed is not None and _seed_is_taken(session, supplied_seed):
        raise ManagerError(
            "fingerprint_seed_conflict",
            "This fingerprint seed is already assigned to another profile.",
            409,
            {"fingerprint_seed": "already_exists"},
        )
    seed = supplied_seed or _new_seed(session)
    tags = _validate_references(
        session,
        folder_id=values.get("folder_id"),
        status_id=values.get("status_id"),
        tag_ids=tag_ids,
        proxy_id=values.get("proxy_id"),
    )
    identity = _fingerprint_identity(seed, values)
    profile = Profile(
        **values,
        fingerprint_seed=identity.seed,
        fingerprint_revision=identity.revision,
        fingerprint_config_hash=identity.config_hash,
        tags=tags,
    )
    session.add(profile)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ManagerError(
            "profile_conflict",
            "The profile could not be saved because a unique value is already in use.",
            409,
        ) from error
    return get_profile(session, profile.id)


def get_profile(session: Session, profile_id: str) -> Profile:
    profile = session.scalar(
        select(Profile)
        .options(selectinload(Profile.tags), selectinload(Profile.runtime_sessions))
        .where(Profile.id == profile_id)
    )
    if profile is None:
        raise ManagerError("profile_not_found", "The requested profile was not found.", 404)
    return profile


def profile_to_dict(
    profile: Profile, *, settings: ManagerSettings | None = None
) -> dict[str, Any]:
    values = {
        "id": profile.id,
        "name": profile.name,
        "folder_id": profile.folder_id,
        "workflow_status_id": profile.status_id,
        "tag_ids": [tag.id for tag in profile.tags],
        "notes": profile.notes,
        "pinned": profile.pinned,
        "startup_urls": profile.startup_urls,
        "fingerprint_seed": profile.fingerprint_seed,
        "fingerprint_preset": profile.fingerprint_preset,
        "fingerprint_revision": profile.fingerprint_revision,
        "fingerprint_config_hash": profile.fingerprint_config_hash,
        "browser_version_mode": profile.browser_version_mode,
        "browser_version": profile.browser_version,
        "user_agent_mode": profile.user_agent_mode,
        "custom_user_agent": profile.custom_user_agent,
        "location": profile.location,
        "window": profile.window,
        "behavior": profile.behavior,
        "proxy_id": profile.proxy_id,
        "test_proxy_before_launch": profile.test_proxy_before_launch,
        "runtime_state": profile.runtime_state,
        "created_at": _canonical_utc(profile.created_at),
        "updated_at": _canonical_utc(profile.updated_at),
        "last_opened_at": (
            _canonical_utc(profile.last_opened_at)
            if profile.last_opened_at is not None
            else None
        ),
        "total_runtime_seconds": profile.total_runtime_seconds,
        "deleted_at": (
            _canonical_utc(profile.deleted_at)
            if profile.deleted_at is not None
            else None
        ),
    }
    if settings is not None:
        values["profile_directory"] = str(
            resolve_profile_directory(settings, profile.id)
        )
    return values


def list_profiles(
    session: Session,
    *,
    query: str | None,
    folder_id: str | None,
    tag_id: str | None,
    workflow_status_id: str | None,
    pinned: bool | None,
    sort: str,
    page: int,
    page_size: int,
    settings: ManagerSettings | None = None,
) -> dict[str, Any]:
    statement = select(Profile).options(
        selectinload(Profile.tags), selectinload(Profile.runtime_sessions)
    ).where(Profile.deleted_at.is_(None))
    count_statement = select(func.count(func.distinct(Profile.id))).where(Profile.deleted_at.is_(None))
    conditions = []
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(
            or_(
                Profile.name.ilike(f"%{escaped}%", escape="\\"),
                Profile.notes.ilike(f"%{escaped}%", escape="\\"),
            )
        )
    if folder_id:
        conditions.append(Profile.folder_id == folder_id)
    if workflow_status_id:
        conditions.append(Profile.status_id == workflow_status_id)
    if pinned is not None:
        conditions.append(Profile.pinned == pinned)
    if tag_id:
        statement = statement.join(Profile.tags)
        count_statement = count_statement.join(Profile.tags)
        conditions.append(Tag.id == tag_id)
    if conditions:
        statement = statement.where(*conditions)
        count_statement = count_statement.where(*conditions)
    descending = sort.startswith("-")
    sort_name = sort[1:] if descending else sort
    column = _SORT_FIELDS.get(sort_name)
    if column is None:
        raise ManagerError(
            "invalid_profile_sort",
            "The requested profile sort field is not supported.",
            422,
            {"sort": "unsupported"},
        )
    order = column.desc() if descending else column.asc()
    total = int(session.scalar(count_statement) or 0)
    profiles = list(
        session.scalars(
            statement.order_by(Profile.pinned.desc(), order, Profile.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).unique()
    )
    return {
        "items": [profile_to_dict(profile, settings=settings) for profile in profiles],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


def _canonical_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _current_safe_profile(profile: Profile, settings: ManagerSettings) -> dict[str, Any]:
    return ProfileRead.model_validate(
        profile_to_dict(profile, settings=settings)
    ).model_dump(mode="json")


def _raise_profile_conflict(profile: Profile, settings: ManagerSettings) -> None:
    raise ManagerError(
        "profile_conflict",
        "The profile was changed by another editor. Refresh and try again.",
        409,
        {"current_profile": _current_safe_profile(profile, settings)},
    )


def _validate_identity_modes(profile: Profile, changes: dict[str, Any]) -> None:
    browser_version_mode = changes.get(
        "browser_version_mode", profile.browser_version_mode
    )
    browser_version = changes.get("browser_version", profile.browser_version)
    user_agent_mode = changes.get("user_agent_mode", profile.user_agent_mode)
    custom_user_agent = changes.get("custom_user_agent", profile.custom_user_agent)
    errors: dict[str, str] = {}
    if browser_version_mode == "pinned" and browser_version is None:
        errors["browser_version"] = "required_for_pinned_mode"
    elif browser_version_mode == "installed" and browser_version is not None:
        errors["browser_version"] = "requires_pinned_mode"
    if user_agent_mode == "custom" and custom_user_agent is None:
        errors["custom_user_agent"] = "required_for_custom_mode"
    elif user_agent_mode == "automatic" and custom_user_agent is not None:
        errors["custom_user_agent"] = "requires_custom_mode"
    if errors:
        raise ManagerError(
            "validation_error",
            "One or more request fields are invalid.",
            422,
            errors,
        )


def update_profile(
    session: Session,
    profile_id: str,
    payload: ProfilePatch,
    *,
    settings: ManagerSettings,
) -> Profile:
    profile = get_profile(session, profile_id)
    if _canonical_utc(payload.expected_updated_at) != _canonical_utc(profile.updated_at):
        _raise_profile_conflict(profile, settings)

    provided_fields = payload.model_fields_set - {"expected_updated_at"}
    changes = {field: getattr(payload, field) for field in provided_fields}
    tag_ids_were_provided = "tag_ids" in changes
    tag_ids = changes.pop("tag_ids", None)
    if "workflow_status_id" in changes:
        changes["status_id"] = changes.pop("workflow_status_id")
    for nested in ("location", "window", "behavior"):
        if nested in changes:
            changes[nested] = getattr(payload, nested).model_dump(mode="json")

    _validate_identity_modes(profile, changes)
    tags = None
    if (
        tag_ids_were_provided
        or "folder_id" in changes
        or "status_id" in changes
        or "proxy_id" in changes
    ):
        tags = _validate_references(
            session,
            folder_id=changes.get("folder_id", profile.folder_id),
            status_id=changes.get("status_id", profile.status_id),
            tag_ids=tag_ids if tag_ids_were_provided else [tag.id for tag in profile.tags],
            proxy_id=changes.get("proxy_id", profile.proxy_id),
        )

    semantic_changes = {
        field: value
        for field, value in changes.items()
        if getattr(profile, field) != value
    }
    tags_changed = tags is not None and {
        tag.id for tag in tags
    } != {tag.id for tag in profile.tags}

    stored_updated_at = profile.updated_at
    guard = session.execute(
        sql_update(Profile)
        .where(Profile.id == profile.id, Profile.updated_at == stored_updated_at)
        .values(updated_at=Profile.updated_at)
        .execution_options(synchronize_session=False)
    )
    if guard.rowcount != 1:
        session.rollback()
        _raise_profile_conflict(get_profile(session, profile_id), settings)

    for field, value in semantic_changes.items():
        setattr(profile, field, value)
    if tags_changed:
        profile.tags = tags

    if semantic_changes or tags_changed:
        if _FINGERPRINT_FIELDS.intersection(semantic_changes):
            values = profile_to_dict(profile)
            identity = _fingerprint_identity(profile.fingerprint_seed, values)
            if identity.config_hash != profile.fingerprint_config_hash:
                profile.fingerprint_revision += 1
                profile.fingerprint_config_hash = identity.config_hash
        profile.updated_at = utc_now()

    session.commit()
    return get_profile(session, profile.id)


def duplicate_profile(session: Session, profile_id: str) -> Profile:
    source = get_profile(session, profile_id)
    payload = ProfileCreate(
        name=f"{source.name} Copy"[:80],
        folder_id=source.folder_id,
        workflow_status_id=source.status_id,
        tag_ids=[tag.id for tag in source.tags],
        notes=source.notes,
        pinned=False,
        startup_urls=source.startup_urls,
        fingerprint_preset=source.fingerprint_preset,
        browser_version_mode=source.browser_version_mode,
        browser_version=source.browser_version,
        user_agent_mode=source.user_agent_mode,
        custom_user_agent=source.custom_user_agent,
        location=source.location,
        window=source.window,
        behavior=source.behavior,
        proxy_id=source.proxy_id,
        test_proxy_before_launch=source.test_proxy_before_launch,
    )
    return create_profile(session, payload)


def regenerate_fingerprint(session: Session, profile_id: str) -> Profile:
    profile = get_profile(session, profile_id)
    profile.fingerprint_seed = _new_seed(session)
    values = profile_to_dict(profile)
    identity = _fingerprint_identity(profile.fingerprint_seed, values)
    profile.fingerprint_revision = identity.revision
    profile.fingerprint_config_hash = identity.config_hash
    session.commit()
    return get_profile(session, profile.id)


def set_trash_state(session: Session, profile_id: str, deleted: bool) -> Profile:
    profile = get_profile(session, profile_id)
    profile.deleted_at = datetime.now(timezone.utc) if deleted else None
    session.commit()
    return get_profile(session, profile.id)


def bulk_update(
    session: Session, payload: BulkProfileRequest
) -> tuple[list[str], int]:
    unique_ids = list(dict.fromkeys(payload.ids))
    profiles = list(session.scalars(select(Profile).where(Profile.id.in_(unique_ids))))
    if len(profiles) != len(unique_ids):
        raise ManagerError(
            "profile_not_found",
            "One or more requested profiles were not found.",
            404,
        )
    if payload.action == "move_folder":
        _validate_references(
            session,
            folder_id=payload.folder_id,
            status_id=None,
            tag_ids=[],
            proxy_id=None,
        )
    if payload.action == "set_status":
        _validate_references(
            session,
            folder_id=None,
            status_id=payload.workflow_status_id,
            tag_ids=[],
            proxy_id=None,
        )
    now = datetime.now(timezone.utc)
    for profile in profiles:
        if payload.action == "trash":
            profile.deleted_at = now
        elif payload.action == "restore":
            profile.deleted_at = None
        elif payload.action == "pin":
            profile.pinned = True
        elif payload.action == "unpin":
            profile.pinned = False
        elif payload.action == "move_folder":
            profile.folder_id = payload.folder_id
        elif payload.action == "set_status":
            profile.status_id = payload.workflow_status_id
    session.commit()
    return unique_ids, len(unique_ids)
