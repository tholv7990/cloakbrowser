"""Persist owned browser runtime sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_runtime_sessions"
down_revision: str | None = "0004_persistent_owner_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ACTIVE = "state IN ('queued','starting','running','stopping','detached')"


def upgrade() -> None:
    op.create_table(
        "runtime_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("manager_instance_id", sa.String(36), nullable=True),
        sa.Column("manager_pid", sa.Integer(), nullable=True),
        sa.Column("manager_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("browser_pid", sa.Integer(), nullable=True),
        sa.Column("browser_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cdp_endpoint", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("last_message", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued','starting','running','stopping','stopped','crashed','detached')",
            name="ck_runtime_sessions_state",
        ),
    )
    op.create_index(
        "uq_runtime_sessions_active_profile",
        "runtime_sessions",
        ["profile_id"],
        unique=True,
        sqlite_where=sa.text(_ACTIVE),
    )


def downgrade() -> None:
    op.drop_index("uq_runtime_sessions_active_profile", table_name="runtime_sessions")
    op.drop_table("runtime_sessions")
