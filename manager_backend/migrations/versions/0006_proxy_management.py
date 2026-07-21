"""Add reusable proxy management."""

from alembic import op
import sqlalchemy as sa


revision: str = "0006_proxy_management"
down_revision: str | None = "0005_runtime_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proxies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(120, collation="NOCASE"), nullable=False, unique=True),
        sa.Column("scheme", sa.String(16), nullable=False),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("credential_ref", sa.String(36), nullable=True, unique=True),
        sa.Column("test_before_launch", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exit_ip", sa.String(64), nullable=True),
        sa.Column("country", sa.String(80), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("timezone", sa.String(80), nullable=True),
        sa.Column("asn", sa.String(32), nullable=True),
        sa.Column("organization", sa.String(160), nullable=True),
        sa.Column("proxy_type", sa.String(24), nullable=True),
        sa.Column("type_confidence", sa.Float(), nullable=True),
        sa.Column("reputation", sa.String(24), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scheme IN ('direct','http','https','socks5','socks5h')",
            name="ck_proxies_scheme",
        ),
    )
    op.execute("UPDATE profiles SET proxy_id = NULL WHERE proxy_id IS NOT NULL")
    with op.batch_alter_table("profiles") as batch:
        batch.create_foreign_key(
            "fk_profiles_proxy_id_proxies", "proxies", ["proxy_id"], ["id"], ondelete="RESTRICT"
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_constraint("fk_profiles_proxy_id_proxies", type_="foreignkey")
    op.drop_table("proxies")
