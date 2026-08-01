"""Persist optional explicit fingerprint overrides."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0020_fingerprint_overrides"
down_revision: str | None = "0019_shop_check_credential_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("gpu_vendor", sa.String(256), nullable=True))
    op.add_column("profiles", sa.Column("gpu_renderer", sa.String(256), nullable=True))
    op.add_column(
        "profiles", sa.Column("hardware_concurrency", sa.Integer(), nullable=True)
    )
    op.add_column("profiles", sa.Column("device_memory", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("screen_width", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("screen_height", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("browser_brand", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "browser_brand")
    op.drop_column("profiles", "screen_height")
    op.drop_column("profiles", "screen_width")
    op.drop_column("profiles", "device_memory")
    op.drop_column("profiles", "hardware_concurrency")
    op.drop_column("profiles", "gpu_renderer")
    op.drop_column("profiles", "gpu_vendor")
