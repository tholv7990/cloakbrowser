"""Add sanitized profile runtime log entries."""

from alembic import op
import sqlalchemy as sa


revision: str = "0008_runtime_observability"
down_revision: str | None = "0007_proxy_quality_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_log_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("event", sa.String(80), nullable=False),
        sa.Column("message", sa.String(4000), nullable=False),
        sa.CheckConstraint(
            "level IN ('debug','info','warning','error')",
            name="ck_profile_log_entries_level",
        ),
    )
    op.create_index(
        "ix_profile_log_entries_profile_created_at",
        "profile_log_entries",
        ["profile_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_log_entries_profile_created_at", table_name="profile_log_entries")
    op.drop_table("profile_log_entries")
