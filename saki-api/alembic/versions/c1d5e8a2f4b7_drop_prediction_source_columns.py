"""drop_prediction_source_columns

Revision ID: c1d5e8a2f4b7
Revises: 4b3f2d1f7c9a
Create Date: 2026-03-06 21:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d5e8a2f4b7"
down_revision: Union[str, Sequence[str], None] = "4b3f2d1f7c9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 兼容历史重命名前后的约束/索引命名。
    op.execute("ALTER TABLE prediction DROP CONSTRAINT IF EXISTS prediction_set_loop_id_fkey")
    op.execute("ALTER TABLE prediction DROP CONSTRAINT IF EXISTS prediction_set_source_round_id_fkey")
    op.execute("ALTER TABLE prediction DROP CONSTRAINT IF EXISTS prediction_set_source_step_id_fkey")
    op.execute("ALTER TABLE prediction DROP CONSTRAINT IF EXISTS prediction_loop_id_fkey")
    op.execute("ALTER TABLE prediction DROP CONSTRAINT IF EXISTS prediction_source_round_id_fkey")
    op.execute("ALTER TABLE prediction DROP CONSTRAINT IF EXISTS prediction_source_step_id_fkey")

    op.execute("DROP INDEX IF EXISTS ix_prediction_set_loop_id")
    op.execute("DROP INDEX IF EXISTS ix_prediction_set_source_round_id")
    op.execute("DROP INDEX IF EXISTS ix_prediction_set_source_step_id")
    op.execute("DROP INDEX IF EXISTS ix_prediction_loop_id")
    op.execute("DROP INDEX IF EXISTS ix_prediction_source_round_id")
    op.execute("DROP INDEX IF EXISTS ix_prediction_source_step_id")

    op.drop_column("prediction", "source_step_id")
    op.drop_column("prediction", "source_round_id")
    op.drop_column("prediction", "loop_id")


def downgrade() -> None:
    op.add_column("prediction", sa.Column("loop_id", sa.Uuid(), nullable=True))
    op.add_column("prediction", sa.Column("source_round_id", sa.Uuid(), nullable=True))
    op.add_column("prediction", sa.Column("source_step_id", sa.Uuid(), nullable=True))

    op.create_foreign_key("prediction_loop_id_fkey", "prediction", "loop", ["loop_id"], ["id"])
    op.create_foreign_key("prediction_source_round_id_fkey", "prediction", "round", ["source_round_id"], ["id"])
    op.create_foreign_key("prediction_source_step_id_fkey", "prediction", "step", ["source_step_id"], ["id"])

    op.create_index("ix_prediction_loop_id", "prediction", ["loop_id"], unique=False)
    op.create_index("ix_prediction_source_round_id", "prediction", ["source_round_id"], unique=False)
    op.create_index("ix_prediction_source_step_id", "prediction", ["source_step_id"], unique=False)
