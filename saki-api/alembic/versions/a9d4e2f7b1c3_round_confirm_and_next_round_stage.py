"""round_confirm_and_next_round_stage

Revision ID: a9d4e2f7b1c3
Revises: f2b4c8d1e7a9
Create Date: 2026-02-28 23:30:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a9d4e2f7b1c3"
down_revision = "f2b4c8d1e7a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("round", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("round", sa.Column("confirmed_commit_id", sa.Uuid(), nullable=True))
    op.add_column(
        "round",
        sa.Column(
            "confirmed_revealed_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "round",
        sa.Column(
            "confirmed_selected_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "round",
        sa.Column(
            "confirmed_effective_min_required",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(op.f("ix_round_confirmed_at"), "round", ["confirmed_at"], unique=False)
    op.create_index(op.f("ix_round_confirmed_commit_id"), "round", ["confirmed_commit_id"], unique=False)
    op.create_foreign_key(
        "fk_round_confirmed_commit_id_commit",
        "round",
        "commit",
        ["confirmed_commit_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_round_confirmed_commit_id_commit", "round", type_="foreignkey")
    op.drop_index(op.f("ix_round_confirmed_commit_id"), table_name="round")
    op.drop_index(op.f("ix_round_confirmed_at"), table_name="round")
    op.drop_column("round", "confirmed_effective_min_required")
    op.drop_column("round", "confirmed_selected_count")
    op.drop_column("round", "confirmed_revealed_count")
    op.drop_column("round", "confirmed_commit_id")
    op.drop_column("round", "confirmed_at")
