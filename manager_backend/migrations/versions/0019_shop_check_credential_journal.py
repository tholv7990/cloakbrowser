"""Shop-check credential journal.

A durable record of each CredentialStore ref written while provisioning a run,
committed before the secret itself so orphaned secrets can be reconciled at
startup. run_id is a loose reference (no foreign key) so the row survives a
rolled-back run/email transaction.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0019_shop_check_credential_journal"
down_revision: str | None = "0018_shop_check_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shop_check_credential_journal",
        sa.Column("ref", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_shop_check_credential_journal_run",
        "shop_check_credential_journal",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shop_check_credential_journal_run",
        table_name="shop_check_credential_journal",
    )
    op.drop_table("shop_check_credential_journal")
