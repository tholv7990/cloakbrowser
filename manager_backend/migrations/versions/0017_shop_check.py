"""Shop email phone-OTP check automation: runs, workers, emails.

Dedicated tables for the Shop-check feature. The emails table stores only a
SHA-256 fingerprint + a CredentialStore reference + a masked value, never a
plaintext email. Worker rows carry the immutable (run_id, profile_id) ownership
pair used for exact-scope cleanup; profile_id is intentionally not a foreign key
so the ownership record survives the profile's later hard-deletion.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0017_shop_check"
down_revision: str | None = "0016_retire_dead_behavior_fields"
branch_labels = None
depends_on = None


_RUN_STATES = "'queued','preparing','running','completed','completed_with_issues','cancelled','failed'"
_RESULTS = (
    "'phone_otp_required','email_otp_required','login_success','account_not_found',"
    "'email_rejected','captcha_or_challenge','proxy_failed','navigation_failed',"
    "'unknown','cancelled'"
)
_EMAIL_STATES = "'pending','running','terminal'"
_WORKER_STATES = "'pending','proxy_check','profile_create','launching','processing','stopping','terminal'"
_CONFIDENCE = "'exact','ambiguous','unknown'"
_CLEANUP_STATES = "'none','in_progress','partial','done'"


def upgrade() -> None:
    op.create_table(
        "shop_check_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("region", sa.String(2), nullable=True),
        sa.Column("emails_per_profile", sa.Integer(), nullable=False),
        sa.Column("max_parallel", sa.Integer(), nullable=False),
        sa.Column("target_url", sa.String(500), nullable=False),
        sa.Column("profile_prefix", sa.String(80), nullable=True),
        sa.Column("output_dir", sa.String(500), nullable=True),
        sa.Column("total_emails", sa.Integer(), nullable=False),
        sa.Column("terminal_count", sa.Integer(), nullable=False),
        sa.Column("retryable_count", sa.Integer(), nullable=False),
        sa.Column("worker_count", sa.Integer(), nullable=False),
        sa.Column("cleanup_state", sa.String(24), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN ({_RUN_STATES})", name="ck_shop_check_runs_status"),
        sa.CheckConstraint(
            "emails_per_profile BETWEEN 1 AND 5",
            name="ck_shop_check_runs_emails_per_profile",
        ),
        sa.CheckConstraint(
            "max_parallel BETWEEN 1 AND 5", name="ck_shop_check_runs_max_parallel"
        ),
        sa.CheckConstraint(
            f"cleanup_state IN ({_CLEANUP_STATES})", name="ck_shop_check_runs_cleanup_state"
        ),
    )

    op.create_table(
        "shop_check_workers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("shop_check_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=True),
        sa.Column("proxy_id", sa.String(36), nullable=True),
        sa.Column("assigned_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"state IN ({_WORKER_STATES})", name="ck_shop_check_workers_state"),
    )
    op.create_index(
        "uq_shop_check_workers_run_ordinal",
        "shop_check_workers",
        ["run_id", "ordinal"],
        unique=True,
    )
    op.create_index(
        "uq_shop_check_workers_profile_id",
        "shop_check_workers",
        ["profile_id"],
        unique=True,
        sqlite_where=sa.text("profile_id IS NOT NULL"),
    )
    op.create_index(
        "ix_shop_check_workers_run_state", "shop_check_workers", ["run_id", "state"]
    )
    # Profile ownership is immutable once assigned: a trigger aborts any attempt
    # to re-point an already-assigned worker at a different profile, even if
    # application code is wrong. (SQLite `IS NOT` is null-safe, so writing the
    # same value is a no-op and allowed.)
    op.execute(
        """
        CREATE TRIGGER trg_shop_check_workers_profile_immutable
        BEFORE UPDATE OF profile_id ON shop_check_workers
        FOR EACH ROW WHEN OLD.profile_id IS NOT NULL
                      AND NEW.profile_id IS NOT OLD.profile_id
        BEGIN
            SELECT RAISE(ABORT, 'shop_check_workers.profile_id is immutable once assigned');
        END;
        """
    )

    op.create_table(
        "shop_check_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("shop_check_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.String(36),
            sa.ForeignKey("shop_check_workers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("email_fingerprint", sa.String(64), nullable=False),
        sa.Column("credential_ref", sa.String(36), nullable=False),
        sa.Column("email_masked", sa.String(320), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("result", sa.String(24), nullable=True),
        sa.Column("phone_prefix", sa.String(8), nullable=True),
        sa.Column("phone_suffix", sa.String(8), nullable=True),
        sa.Column("phone_country_code", sa.String(2), nullable=True),
        sa.Column("phone_country_name", sa.String(64), nullable=True),
        sa.Column("phone_region_name", sa.String(64), nullable=True),
        sa.Column("phone_confidence", sa.String(16), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"state IN ({_EMAIL_STATES})", name="ck_shop_check_emails_state"),
        sa.CheckConstraint(
            f"result IS NULL OR result IN ({_RESULTS})", name="ck_shop_check_emails_result"
        ),
        sa.CheckConstraint(
            f"phone_confidence IS NULL OR phone_confidence IN ({_CONFIDENCE})",
            name="ck_shop_check_emails_confidence",
        ),
        sa.CheckConstraint(
            "(state = 'terminal' AND result IS NOT NULL AND checked_at IS NOT NULL) "
            "OR (state <> 'terminal' AND result IS NULL)",
            name="ck_shop_check_emails_terminal_coherent",
        ),
    )
    op.create_index(
        "ix_shop_check_emails_run_state", "shop_check_emails", ["run_id", "state"]
    )
    op.create_index(
        "uq_shop_check_emails_run_ordinal",
        "shop_check_emails",
        ["run_id", "ordinal"],
        unique=True,
    )
    op.create_index(
        "uq_shop_check_emails_run_fingerprint",
        "shop_check_emails",
        ["run_id", "email_fingerprint"],
        unique=True,
    )
    op.create_index("ix_shop_check_emails_worker", "shop_check_emails", ["worker_id"])


def downgrade() -> None:
    op.drop_index("ix_shop_check_emails_worker", table_name="shop_check_emails")
    op.drop_index("uq_shop_check_emails_run_fingerprint", table_name="shop_check_emails")
    op.drop_index("uq_shop_check_emails_run_ordinal", table_name="shop_check_emails")
    op.drop_index("ix_shop_check_emails_run_state", table_name="shop_check_emails")
    op.drop_table("shop_check_emails")
    op.execute("DROP TRIGGER IF EXISTS trg_shop_check_workers_profile_immutable")
    op.drop_index("ix_shop_check_workers_run_state", table_name="shop_check_workers")
    op.drop_index("uq_shop_check_workers_profile_id", table_name="shop_check_workers")
    op.drop_index("uq_shop_check_workers_run_ordinal", table_name="shop_check_workers")
    op.drop_table("shop_check_workers")
    op.drop_table("shop_check_runs")
