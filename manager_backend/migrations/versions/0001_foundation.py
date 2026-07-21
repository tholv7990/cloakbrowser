"""Create the original manager foundation tables.

This migration is deliberately self-contained. Historical migrations must not import
live ORM metadata because later model changes would alter fresh-install history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("color", sa.String(7), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "workflow_statuses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "folder_id",
            sa.String(36),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status_id",
            sa.String(36),
            sa.ForeignKey("workflow_statuses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("startup_url", sa.Text(), nullable=True),
        sa.Column("windows_persona", sa.String(16), nullable=False),
        sa.Column("fingerprint_seed", sa.String(20), nullable=False),
        sa.Column("fingerprint_preset", sa.String(16), nullable=False),
        sa.Column("identity_json", sa.JSON(), nullable=False),
        sa.Column("hardware_json", sa.JSON(), nullable=False),
        sa.Column("advanced_json", sa.JSON(), nullable=False),
        sa.Column("proxy_id", sa.String(36), nullable=True),
        sa.Column("test_proxy_before_launch", sa.Boolean(), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_runtime_seconds", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "windows_persona IN ('windows_10', 'windows_11')",
            name="ck_profiles_windows_persona",
        ),
        sa.CheckConstraint(
            "fingerprint_preset IN ('default', 'consistent')",
            name="ck_profiles_fingerprint_preset",
        ),
    )
    op.create_table(
        "profile_tags",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.String(36),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("profile_tags")
    op.drop_table("profiles")
    op.drop_table("workflow_statuses")
    op.drop_table("tags")
    op.drop_table("folders")
