"""Shop-check hardening (split out of the published 0017).

Adds, on top of the original 0017 tables:
  - the `email_rejected` result value,
  - unique (run_id, ordinal) on emails and workers,
  - unique (run_id, email_fingerprint) on emails,
  - a partial-unique index making a non-null worker profile_id globally unique,
  - a terminal/result/checked_at coherence constraint (non-terminal rows carry
    neither a result nor a checked_at),
  - a trigger making an assigned worker profile_id immutable.

SQLite cannot ALTER a CHECK constraint, so the emails table is rebuilt safely
(create-new -> copy-all-rows -> drop-old -> rename), preserving every row, FK,
and column. Worker changes are additive (indexes + trigger) and need no rebuild.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0018_shop_check_hardening"
down_revision: str | None = "0017_shop_check"
branch_labels = None
depends_on = None


_RESULTS_V2 = (
    "'phone_otp_required','email_otp_required','login_success','account_not_found',"
    "'email_rejected','captcha_or_challenge','proxy_failed','navigation_failed',"
    "'unknown','cancelled'"
)
_RESULTS_V1 = (
    "'phone_otp_required','email_otp_required','login_success','account_not_found',"
    "'captcha_or_challenge','proxy_failed','navigation_failed','unknown','cancelled'"
)
_COHERENCE = (
    "(state = 'terminal' AND result IS NOT NULL AND checked_at IS NOT NULL) "
    "OR (state IN ('pending','running') AND result IS NULL AND checked_at IS NULL)"
)

# Explicit column list so copy is order-independent and total.
_EMAIL_COLS = (
    "id, run_id, worker_id, ordinal, email_fingerprint, credential_ref, email_masked, "
    "state, result, phone_prefix, phone_suffix, phone_country_code, phone_country_name, "
    "phone_region_name, phone_confidence, retry_count, error, checked_at, created_at"
)

_TRIGGER_SQL = """
CREATE TRIGGER trg_shop_check_workers_profile_immutable
BEFORE UPDATE OF profile_id ON shop_check_workers
FOR EACH ROW WHEN OLD.profile_id IS NOT NULL
              AND NEW.profile_id IS NOT OLD.profile_id
BEGIN
    SELECT RAISE(ABORT, 'shop_check_workers.profile_id is immutable once assigned');
END;
"""


def _emails_table_sql(*, results: str, coherence: str | None) -> str:
    coherence_line = (
        f",\n    CONSTRAINT ck_shop_check_emails_terminal_coherent CHECK ({coherence})"
        if coherence
        else ""
    )
    return f"""
    CREATE TABLE shop_check_emails_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL REFERENCES shop_check_runs(id) ON DELETE CASCADE,
        worker_id VARCHAR(36) REFERENCES shop_check_workers(id) ON DELETE SET NULL,
        ordinal INTEGER NOT NULL,
        email_fingerprint VARCHAR(64) NOT NULL,
        credential_ref VARCHAR(36) NOT NULL,
        email_masked VARCHAR(320) NOT NULL,
        state VARCHAR(16) NOT NULL,
        result VARCHAR(24),
        phone_prefix VARCHAR(8),
        phone_suffix VARCHAR(8),
        phone_country_code VARCHAR(2),
        phone_country_name VARCHAR(64),
        phone_region_name VARCHAR(64),
        phone_confidence VARCHAR(16),
        retry_count INTEGER NOT NULL,
        error VARCHAR(1000),
        checked_at DATETIME,
        created_at DATETIME NOT NULL,
        CONSTRAINT ck_shop_check_emails_state CHECK (state IN ('pending','running','terminal')),
        CONSTRAINT ck_shop_check_emails_result CHECK (result IS NULL OR result IN ({results})),
        CONSTRAINT ck_shop_check_emails_confidence CHECK (phone_confidence IS NULL OR phone_confidence IN ('exact','ambiguous','unknown')){coherence_line}
    )
    """


def _rebuild_emails(*, results: str, coherence: str | None, unique_ordinal: bool) -> None:
    op.execute(_emails_table_sql(results=results, coherence=coherence))
    op.execute(
        f"INSERT INTO shop_check_emails_new ({_EMAIL_COLS}) "
        f"SELECT {_EMAIL_COLS} FROM shop_check_emails"
    )
    op.execute("DROP TABLE shop_check_emails")
    op.execute("ALTER TABLE shop_check_emails_new RENAME TO shop_check_emails")
    op.create_index("ix_shop_check_emails_run_state", "shop_check_emails", ["run_id", "state"])
    op.create_index(
        "uq_shop_check_emails_run_ordinal" if unique_ordinal else "ix_shop_check_emails_run_ordinal",
        "shop_check_emails",
        ["run_id", "ordinal"],
        unique=unique_ordinal,
    )
    if unique_ordinal:
        op.create_index(
            "uq_shop_check_emails_run_fingerprint",
            "shop_check_emails",
            ["run_id", "email_fingerprint"],
            unique=True,
        )
    op.create_index("ix_shop_check_emails_worker", "shop_check_emails", ["worker_id"])


def upgrade() -> None:
    # --- workers: additive unique indexes + immutability trigger --------------
    op.drop_index("ix_shop_check_workers_run_ordinal", table_name="shop_check_workers")
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
    op.execute(_TRIGGER_SQL)

    # --- emails: SQLite-safe rebuild for the two new CHECK constraints --------
    op.drop_index("ix_shop_check_emails_run_state", table_name="shop_check_emails")
    op.drop_index("ix_shop_check_emails_run_ordinal", table_name="shop_check_emails")
    op.drop_index("ix_shop_check_emails_worker", table_name="shop_check_emails")
    _rebuild_emails(results=_RESULTS_V2, coherence=_COHERENCE, unique_ordinal=True)


def downgrade() -> None:
    # Revert emails to the original 0017 constraints/indexes.
    op.drop_index("ix_shop_check_emails_worker", table_name="shop_check_emails")
    op.drop_index("uq_shop_check_emails_run_fingerprint", table_name="shop_check_emails")
    op.drop_index("uq_shop_check_emails_run_ordinal", table_name="shop_check_emails")
    op.drop_index("ix_shop_check_emails_run_state", table_name="shop_check_emails")
    _rebuild_emails(results=_RESULTS_V1, coherence=None, unique_ordinal=False)

    # Revert workers to the original 0017 indexes and drop the trigger.
    op.execute("DROP TRIGGER IF EXISTS trg_shop_check_workers_profile_immutable")
    op.drop_index("uq_shop_check_workers_profile_id", table_name="shop_check_workers")
    op.drop_index("uq_shop_check_workers_run_ordinal", table_name="shop_check_workers")
    op.create_index(
        "ix_shop_check_workers_run_ordinal", "shop_check_workers", ["run_id", "ordinal"]
    )
