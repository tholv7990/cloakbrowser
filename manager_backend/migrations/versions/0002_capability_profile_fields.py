"""Align profile fields with supported CloakBrowser capabilities."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_capability_profile_fields"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profiles", recreate="always") as batch:
        batch.drop_constraint("ck_profiles_windows_persona", type_="check")
        batch.drop_column("startup_url")
        batch.drop_column("windows_persona")
        batch.drop_column("identity_json")
        batch.drop_column("hardware_json")
        batch.drop_column("advanced_json")
        batch.add_column(
            sa.Column("startup_urls_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("fingerprint_revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("fingerprint_config_hash", sa.String(64), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("browser_version_mode", sa.String(16), nullable=False, server_default="installed")
        )
        batch.add_column(sa.Column("browser_version", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column("user_agent_mode", sa.String(16), nullable=False, server_default="automatic")
        )
        batch.add_column(sa.Column("custom_user_agent", sa.String(512), nullable=True))
        batch.add_column(
            sa.Column("location_json", sa.JSON(), nullable=False, server_default='{"geo_mode":"system"}')
        )
        batch.add_column(
            sa.Column("window_json", sa.JSON(), nullable=False, server_default='{"mode":"maximized"}')
        )
        batch.add_column(
            sa.Column("behavior_json", sa.JSON(), nullable=False, server_default='{"humanize_enabled":false}')
        )
        batch.create_unique_constraint("uq_profiles_fingerprint_seed", ["fingerprint_seed"])
        batch.create_check_constraint(
            "ck_profiles_browser_version_mode",
            "browser_version_mode IN ('installed', 'pinned')",
        )
        batch.create_check_constraint(
            "ck_profiles_user_agent_mode",
            "user_agent_mode IN ('automatic', 'custom')",
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles", recreate="always") as batch:
        batch.drop_constraint("ck_profiles_user_agent_mode", type_="check")
        batch.drop_constraint("ck_profiles_browser_version_mode", type_="check")
        batch.drop_constraint("uq_profiles_fingerprint_seed", type_="unique")
        batch.drop_column("behavior_json")
        batch.drop_column("window_json")
        batch.drop_column("location_json")
        batch.drop_column("custom_user_agent")
        batch.drop_column("user_agent_mode")
        batch.drop_column("browser_version")
        batch.drop_column("browser_version_mode")
        batch.drop_column("fingerprint_config_hash")
        batch.drop_column("fingerprint_revision")
        batch.drop_column("startup_urls_json")
        batch.add_column(sa.Column("advanced_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("hardware_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("identity_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("windows_persona", sa.String(16), nullable=False, server_default="windows_11"))
        batch.add_column(sa.Column("startup_url", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_profiles_windows_persona",
            "windows_persona IN ('windows_10', 'windows_11')",
        )
