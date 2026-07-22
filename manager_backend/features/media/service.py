"""Media library: virtual camera/mic/screen sources the engine injects.

The manager curates the library, the global on/off, and per-profile assignment.
The actual getUserMedia substitution is engine-side (like fingerprint patches).

ponytail: assets are placeholder registrations (name/kind/format). Real file
upload (multipart → size_bytes/path) and launch-flag wiring are deferred until
the engine exposes media-injection flags.
"""

from __future__ import annotations

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import MediaAsset, MediaSetting, Profile, profile_media_assets


_KIND_MIME_PREFIXES = {
    "camera": ("image/", "video/"),
    "microphone": ("audio/",),
    "screen": ("image/", "video/"),
}


def _validate_kind_format(kind: str, media_format: str) -> str:
    fmt = media_format.strip().lower()
    prefixes = _KIND_MIME_PREFIXES.get(kind, ())
    if "/" not in fmt or not any(fmt.startswith(prefix) for prefix in prefixes):
        raise ManagerError(
            "media_format_mismatch",
            f"{media_format!r} is not a valid MIME type for a {kind} source.",
            422,
        )
    return fmt


def _assigned_count(session: Session, asset_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(profile_media_assets)
            .join(Profile, Profile.id == profile_media_assets.c.profile_id)
            .where(
                profile_media_assets.c.media_asset_id == asset_id,
                Profile.deleted_at.is_(None),
            )
        )
        or 0
    )


def _asset_to_dict(session: Session, asset: MediaAsset) -> dict:
    return {
        "id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        "format": asset.format,
        "size_bytes": asset.size_bytes,
        "assigned_profile_count": _assigned_count(session, asset.id),
        "created_at": asset.created_at,
    }


def _get_asset(session: Session, asset_id: str) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise ManagerError(
            "media_asset_not_found", "The requested media asset was not found.", 404
        )
    return asset


def get_settings(session: Session) -> dict:
    row = session.get(MediaSetting, 1)
    return {"enabled": bool(row.enabled) if row is not None else False}


def update_settings(session: Session, *, enabled: bool) -> dict:
    row = session.get(MediaSetting, 1)
    if row is None:
        row = MediaSetting(id=1, enabled=enabled)
        session.add(row)
    else:
        row.enabled = enabled
    session.commit()
    return {"enabled": row.enabled}


def list_assets(session: Session) -> list[dict]:
    assets = session.scalars(
        select(MediaAsset).order_by(MediaAsset.created_at.desc(), MediaAsset.id)
    ).all()
    return [_asset_to_dict(session, asset) for asset in assets]


def create_asset(session: Session, *, name: str, kind: str, media_format: str) -> dict:
    fmt = _validate_kind_format(kind, media_format)
    asset = MediaAsset(name=name.strip(), kind=kind, format=fmt, size_bytes=0, path=None)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return _asset_to_dict(session, asset)


def delete_asset(session: Session, asset_id: str) -> None:
    asset = _get_asset(session, asset_id)
    session.execute(
        delete(profile_media_assets).where(
            profile_media_assets.c.media_asset_id == asset_id
        )
    )
    session.delete(asset)
    session.commit()


def get_assignments(session: Session, asset_id: str) -> list[str]:
    _get_asset(session, asset_id)
    return list(
        session.scalars(
            select(profile_media_assets.c.profile_id)
            .join(Profile, Profile.id == profile_media_assets.c.profile_id)
            .where(
                profile_media_assets.c.media_asset_id == asset_id,
                Profile.deleted_at.is_(None),
            )
            .order_by(profile_media_assets.c.profile_id)
        )
    )


def set_assignments(session: Session, asset_id: str, profile_ids: list[str]) -> dict:
    asset = _get_asset(session, asset_id)
    # Keep only ids that exist and are not trashed; prune unknown/duplicate ids.
    valid = set(
        session.scalars(
            select(Profile.id).where(
                Profile.id.in_(profile_ids), Profile.deleted_at.is_(None)
            )
        )
    )
    session.execute(
        delete(profile_media_assets).where(
            profile_media_assets.c.media_asset_id == asset_id
        )
    )
    if valid:
        session.execute(
            insert(profile_media_assets),
            [{"profile_id": pid, "media_asset_id": asset_id} for pid in valid],
        )
    session.commit()
    return _asset_to_dict(session, asset)
