"""Add the Shopify Builder: stores, AI settings, draft build plans + steps."""

from alembic import op
import sqlalchemy as sa


revision: str = "0014_shopify"
down_revision: str | None = "0013_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopify_stores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("shop_domain", sa.String(255), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("shop_info_json", sa.JSON(), nullable=False),
        sa.Column("inspection_json", sa.JSON(), nullable=False),
        sa.Column("proxy_id", sa.String(36), nullable=True),
        sa.Column("credentials_ref", sa.String(36), nullable=False),
        sa.Column("token_ref", sa.String(36), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("niche", sa.String(120), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("store_name", sa.String(160), nullable=False),
        sa.Column("support_email", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_shopify_stores_domain", "shopify_stores", ["shop_domain"], unique=True
    )
    op.create_table(
        "shopify_ai_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("api_key_ref", sa.String(36), nullable=True),
    )
    op.create_table(
        "shopify_build_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "store_id",
            sa.String(36),
            sa.ForeignKey("shopify_stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('staged','running','completed','partial','failed')",
            name="ck_shopify_build_plans_status",
        ),
    )
    op.create_table(
        "shopify_plan_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("shopify_build_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("shopify_plan_steps")
    op.drop_table("shopify_build_plans")
    op.drop_table("shopify_ai_settings")
    op.drop_index("uq_shopify_stores_domain", table_name="shopify_stores")
    op.drop_table("shopify_stores")
