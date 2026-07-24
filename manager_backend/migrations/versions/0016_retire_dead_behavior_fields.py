"""Retire the dead behavior/window fields (F-006).

The humanize / hardware-concurrency / GPU / downloads / additional-args / cache /
https / restore-tabs behavior fields and the window color_scheme were stored but
never applied at launch; two of them also polluted the fingerprint config hash.
This strips them from every stored profile and re-baselines fingerprint_config_hash
under FINGERPRINT_REVISION 2. Seeds are never touched. Irreversible for the removed
values (they carried no runtime effect); the reduced JSON is still readable by the
old schema (its fields had defaults), so downgrade needs no data change.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

from manager_backend.fingerprints import build_fingerprint_identity


revision: str = "0016_retire_dead_behavior_fields"
down_revision: str | None = "0015_performance_indexes"
branch_labels = None
depends_on = None


_RETIRED_BEHAVIOR_KEYS = (
    "humanize_enabled",
    "humanize_preset",
    "clear_cache_before_launch",
    "restore_previous_tabs",
    "download_directory_mode",
    "custom_download_directory",
    "ignore_https_errors",
    "hardware_concurrency_mode",
    "hardware_concurrency",
    "gpu_mode",
    "gpu_vendor",
    "additional_args",
)
_RETIRED_WINDOW_KEYS = ("color_scheme",)


def _as_dict(blob: object) -> dict:
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except ValueError:
            return {}
    return blob if isinstance(blob, dict) else {}


def _stripped(blob: object, keys: tuple[str, ...]) -> dict:
    data = _as_dict(blob)
    return {key: value for key, value in data.items() if key not in keys}


def upgrade() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, fingerprint_seed, fingerprint_preset, browser_version_mode, "
                "browser_version, user_agent_mode, custom_user_agent, location_json, "
                "window_json, behavior_json FROM profiles"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        behavior = _stripped(row["behavior_json"], _RETIRED_BEHAVIOR_KEYS)
        window = _stripped(row["window_json"], _RETIRED_WINDOW_KEYS)
        location = _as_dict(row["location_json"])
        identity = build_fingerprint_identity(
            seed=row["fingerprint_seed"],
            fingerprint_preset=row["fingerprint_preset"],
            browser_version_mode=row["browser_version_mode"],
            browser_version=row["browser_version"],
            user_agent_mode=row["user_agent_mode"],
            custom_user_agent=row["custom_user_agent"],
            location=location,
            window=window,
            behavior=behavior,
        )
        bind.execute(
            sa.text(
                "UPDATE profiles SET behavior_json = :behavior, window_json = :window, "
                "fingerprint_config_hash = :config_hash WHERE id = :id"
            ),
            {
                "behavior": json.dumps(behavior),
                "window": json.dumps(window),
                "config_hash": identity.config_hash,
                "id": row["id"],
            },
        )


def downgrade() -> None:
    # The retired values carried no runtime effect and are not restored. The reduced
    # JSON is readable by the old schema (its fields defaulted), so no data change is
    # needed; the config hash re-baselines on the next identity edit.
    pass
