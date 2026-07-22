"""Persist fingerprint diagnostic runs."""

from alembic import op
import sqlalchemy as sa


revision: str = "0010_diagnostics"
down_revision: str | None = "0009_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("target_url", sa.String(2048), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(500), nullable=True),
        sa.Column("findings_json", sa.JSON(), nullable=False),
        sa.Column("screenshot_path", sa.String(2048), nullable=True),
        sa.Column("report_path", sa.String(2048), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.CheckConstraint(
            "kind IN ('direct_google_control','pixelscan','iphey','cloudflare','google_search')",
            name="ck_diagnostic_runs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','passed','warning','failed','cancelled')",
            name="ck_diagnostic_runs_status",
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_diagnostic_runs_progress",
        ),
        sa.CheckConstraint(
            "(kind = 'direct_google_control' AND target_url = "
            "'https://www.google.com/search?q=CloakBrowser+diagnostic') OR "
            "(kind = 'pixelscan' AND target_url = 'https://pixelscan.net/') OR "
            "(kind = 'iphey' AND target_url = 'https://iphey.com/') OR "
            "(kind = 'cloudflare' AND target_url = "
            "'https://challenge.cloudflare.com/turnstile/v0/generic/') OR "
            "(kind = 'google_search' AND target_url = "
            "'https://www.google.com/search?q=CloakBrowser+browser+diagnostic')",
            name="ck_diagnostic_runs_target_url",
        ),
    )
    op.create_index(
        "uq_diagnostic_runs_active_profile",
        "diagnostic_runs",
        ["profile_id"],
        unique=True,
        sqlite_where=sa.text(
            "profile_id IS NOT NULL AND status IN ('queued','running')"
        ),
    )
    op.create_index(
        "ix_diagnostic_runs_requested_at",
        "diagnostic_runs",
        ["requested_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_diagnostic_runs_requested_at", table_name="diagnostic_runs")
    op.drop_index("uq_diagnostic_runs_active_profile", table_name="diagnostic_runs")
    op.drop_table("diagnostic_runs")
