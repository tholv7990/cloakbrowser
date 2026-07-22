"""Give profile logs a persistent monotonic sequence."""

from alembic import op
import sqlalchemy as sa


revision: str = "0011_profile_log_sequence"
down_revision: str | None = "0010_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profile_log_entries",
        sa.Column("sequence", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE profile_log_entries AS current
            SET sequence = (
                SELECT COUNT(*)
                FROM profile_log_entries AS preceding
                WHERE preceding.profile_id = current.profile_id
                  AND (
                    preceding.created_at < current.created_at
                    OR (
                      preceding.created_at = current.created_at
                      AND preceding.id <= current.id
                    )
                  )
            )
            """
        )
    )
    with op.batch_alter_table("profile_log_entries") as batch:
        batch.alter_column("sequence", existing_type=sa.Integer(), nullable=False)
    op.create_index(
        "uq_profile_log_entries_profile_sequence",
        "profile_log_entries",
        ["profile_id", "sequence"],
        unique=True,
    )
    op.create_table(
        "profile_log_sequences",
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "next_sequence >= 1", name="ck_profile_log_sequences_next_sequence"
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO profile_log_sequences (profile_id, next_sequence)
            SELECT profile_id, MAX(sequence) + 1
            FROM profile_log_entries
            GROUP BY profile_id
            """
        )
    )


def downgrade() -> None:
    op.drop_table("profile_log_sequences")
    op.drop_index(
        "uq_profile_log_entries_profile_sequence",
        table_name="profile_log_entries",
    )
    with op.batch_alter_table("profile_log_entries") as batch:
        batch.drop_column("sequence")
