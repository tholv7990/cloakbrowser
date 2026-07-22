"""Add automation: templates, recordings, runs, credential pool, factory."""

from alembic import op
import sqlalchemy as sa


revision: str = "0013_automation"
down_revision: str | None = "0012_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "automation_recordings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('recording','stopped','cancelled')",
            name="ck_automation_recordings_status",
        ),
    )
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("automation_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("max_parallel", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("attention_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled')",
            name="ck_automation_runs_status",
        ),
    )
    op.create_table(
        "automation_run_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("automation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("last_completed_step", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("attention_reason", sa.String(300), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("screenshot_path", sa.String(500), nullable=True),
        sa.Column("credential_ref", sa.String(36), nullable=True),
        sa.Column("variables_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "automation_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reserved_run_id", sa.String(36), nullable=True),
        sa.Column("reserved_profile_id", sa.String(36), nullable=True),
        sa.Column("credential_ref", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('available','reserved','used','failed')",
            name="ck_automation_credentials_status",
        ),
    )
    op.create_index(
        "uq_automation_credentials_fingerprint",
        "automation_credentials",
        ["fingerprint_sha256"],
        unique=True,
    )
    op.create_table(
        "profile_factory_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("name_prefix", sa.String(120), nullable=False),
        sa.Column("automation_template_id", sa.String(36), nullable=True),
        sa.Column("start_automation", sa.Boolean(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled')",
            name="ck_profile_factory_jobs_status",
        ),
    )
    op.create_table(
        "profile_factory_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("profile_factory_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("profile_factory_items")
    op.drop_table("profile_factory_jobs")
    op.drop_index(
        "uq_automation_credentials_fingerprint", table_name="automation_credentials"
    )
    op.drop_table("automation_credentials")
    op.drop_table("automation_run_items")
    op.drop_table("automation_runs")
    op.drop_table("automation_recordings")
    op.drop_table("automation_templates")
