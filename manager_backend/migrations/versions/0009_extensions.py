"""Add unpacked extension metadata and profile assignments."""

from alembic import op
import sqlalchemy as sa


revision: str = "0009_extensions"
down_revision: str | None = "0008_runtime_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extensions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("directory", sa.String(2048, collation="NOCASE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("manifest_version", sa.Integer(), nullable=False),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "manifest_version IN (2, 3)", name="ck_extensions_manifest_version"
        ),
    )
    op.create_index("uq_extensions_directory", "extensions", ["directory"], unique=True)
    op.create_table(
        "profile_extensions",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "extension_id",
            sa.String(36),
            sa.ForeignKey("extensions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("profile_extensions")
    op.drop_index("uq_extensions_directory", table_name="extensions")
    op.drop_table("extensions")
