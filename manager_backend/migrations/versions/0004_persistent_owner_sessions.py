"""Keep local owner sessions until explicit revocation."""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision: str = "0004_persistent_owner_sessions"
down_revision: str | None = "0003_local_owner_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_column("absolute_expires_at")
        batch.drop_column("last_seen_at")


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=True)
        )

    now = datetime.now(timezone.utc)
    future = datetime(9999, 12, 31, tzinfo=timezone.utc)
    op.execute(
        sa.text(
            "UPDATE auth_sessions SET last_seen_at = :now, absolute_expires_at = :future"
        ).bindparams(now=now, future=future)
    )
    with op.batch_alter_table("auth_sessions") as batch:
        batch.alter_column("last_seen_at", nullable=False)
        batch.alter_column("absolute_expires_at", nullable=False)
