"""Update-release metadata: publish a signed release, fetch the latest per channel.

The desktop verifies the manifest's Ed25519 signature itself; the endpoint is public
(the version/url/hash/signature are not secret). This is separate from — and does
NOT weaken — the CloakBrowser browser-binary's own Ed25519-then-SHA256 verification.
"""

from __future__ import annotations

from sqlalchemy import select

from ... import models
from ...audit import record

CHANNELS = ("stable", "beta")


def publish_release(
    session,
    *,
    channel: str,
    version: str,
    min_supported_version: str,
    artifact_url: str,
    sha256: str,
    signature: str,
    actor: str = "admin",
) -> models.UpdateRelease:
    if channel not in CHANNELS:
        raise ValueError(f"invalid channel: {channel}")
    release = models.UpdateRelease(
        channel=channel,
        version=version,
        min_supported_version=min_supported_version,
        artifact_url=artifact_url,
        sha256=sha256,
        signature=signature,
    )
    session.add(release)
    session.flush()
    record(
        session,
        actor=actor,
        action="release.publish",
        subject_type="update_release",
        subject_id=release.id,
        data={"channel": channel, "version": version},
    )
    return release


def get_latest_release(session, *, channel: str) -> models.UpdateRelease | None:
    return session.scalars(
        select(models.UpdateRelease)
        .where(models.UpdateRelease.channel == channel)
        .order_by(models.UpdateRelease.published_at.desc())
    ).first()


def _parse_version(value: str) -> tuple[int, ...]:
    parts = []
    for segment in value.lstrip("vV").split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """Numeric-dotted version compare (pre-release tags ignored for v1)."""
    return _parse_version(candidate) > _parse_version(current)


def tauri_manifest(release: models.UpdateRelease) -> dict:
    """Map a release row to Tauri v2's dynamic-update JSON shape."""
    return {
        "version": release.version,
        "pub_date": release.published_at.isoformat(),
        "url": release.artifact_url,
        "signature": release.signature,  # Tauri minisign signature of the installer
        "notes": "",
    }
