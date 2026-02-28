"""round_selection_override_and_round_state_cleanup

Revision ID: f2b4c8d1e7a9
Revises: e1f9a6b3c4d2
Create Date: 2026-02-28 18:05:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f2b4c8d1e7a9"
down_revision = "e1f9a6b3c4d2"
branch_labels = None
depends_on = None


round_selection_override_op_enum = postgresql.ENUM(
    "INCLUDE",
    "EXCLUDE",
    name="roundselectionoverrideop",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        round_selection_override_op_enum.create(bind, checkfirst=True)

    op.execute(
        """
        UPDATE round
        SET state = 'COMPLETED'::roundstatus,
            updated_at = now()
        WHERE state = 'WAIT_USER'::roundstatus
        """
    )

    op.create_table(
        "al_round_selection_override",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=False),
        sa.Column("op", round_selection_override_op_enum if dialect == "postgresql" else sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=4000), nullable=True),
        sa.ForeignKeyConstraint(["round_id"], ["round.id"]),
        sa.ForeignKeyConstraint(["sample_id"], ["sample.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "sample_id", name="uq_al_round_selection_override_round_sample"),
    )
    op.create_index(op.f("ix_al_round_selection_override_round_id"), "al_round_selection_override", ["round_id"], unique=False)
    op.create_index(op.f("ix_al_round_selection_override_sample_id"), "al_round_selection_override", ["sample_id"], unique=False)
    op.create_index(op.f("ix_al_round_selection_override_op"), "al_round_selection_override", ["op"], unique=False)
    op.create_index(op.f("ix_al_round_selection_override_created_by"), "al_round_selection_override", ["created_by"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.drop_index(op.f("ix_al_round_selection_override_created_by"), table_name="al_round_selection_override")
    op.drop_index(op.f("ix_al_round_selection_override_op"), table_name="al_round_selection_override")
    op.drop_index(op.f("ix_al_round_selection_override_sample_id"), table_name="al_round_selection_override")
    op.drop_index(op.f("ix_al_round_selection_override_round_id"), table_name="al_round_selection_override")
    op.drop_table("al_round_selection_override")

    if dialect == "postgresql":
        round_selection_override_op_enum.drop(bind, checkfirst=True)

