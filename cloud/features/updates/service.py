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
