"""Add indexes for manager list, assignment, and runtime-history queries."""

from alembic import op


revision: str = "0015_performance_indexes"
down_revision: str | None = "0014_shopify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_profiles_proxy_id", "profiles", ["proxy_id"], if_not_exists=True
    )
    op.create_index(
        "ix_runtime_sessions_profile_created_at",
        "runtime_sessions",
        ["profile_id", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_runtime_sessions_profile_state",
        "runtime_sessions",
        ["profile_id", "state"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_runtime_sessions_created_at_id",
        "runtime_sessions",
        ["created_at", "id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_runtime_sessions_updated_at",
        "runtime_sessions",
        ["updated_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_profile_media_assets_media_profile",
        "profile_media_assets",
        ["media_asset_id", "profile_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profile_media_assets_media_profile",
        table_name="profile_media_assets",
    )
    op.drop_index(
        "ix_runtime_sessions_created_at_id",
        table_name="runtime_sessions",
    )
    op.drop_index(
        "ix_runtime_sessions_updated_at",
        table_name="runtime_sessions",
    )
    op.drop_index(
        "ix_runtime_sessions_profile_state",
        table_name="runtime_sessions",
    )
    op.drop_index(
        "ix_runtime_sessions_profile_created_at",
        table_name="runtime_sessions",
    )
    op.drop_index("ix_profiles_proxy_id", table_name="profiles")
