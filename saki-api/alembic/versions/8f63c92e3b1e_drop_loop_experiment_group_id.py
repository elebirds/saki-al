"""drop_loop_experiment_group_id

Revision ID: 8f63c92e3b1e
Revises: 3571be625207
Create Date: 2026-03-05 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f63c92e3b1e"
down_revision: Union[str, Sequence[str], None] = "3571be625207"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_loop_experiment_group_id"), table_name="loop")
    op.drop_column("loop", "experiment_group_id")


def downgrade() -> None:
    op.add_column("loop", sa.Column("experiment_group_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_loop_experiment_group_id"),
        "loop",
        ["experiment_group_id"],
        unique=False,
    )
