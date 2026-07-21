"""Add asynchronous proxy quality runs."""

from alembic import op
import sqlalchemy as sa


revision: str = "0007_proxy_quality_runs"
down_revision: str | None = "0006_proxy_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proxy_quality_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("proxy_id", sa.String(36), sa.ForeignKey("proxies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("last_message", sa.String(80), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued','running','completed','failed','cancelled')",
            name="ck_proxy_quality_runs_state",
        ),
    )
    op.create_index(
        "uq_proxy_quality_runs_active_proxy",
        "proxy_quality_runs",
        ["proxy_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued','running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_proxy_quality_runs_active_proxy", table_name="proxy_quality_runs")
    op.drop_table("proxy_quality_runs")
