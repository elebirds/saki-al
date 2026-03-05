"""rename_prediction_set_id_columns

Revision ID: 9f4d7b2c6a1e
Revises: c1d5e8a2f4b7
Create Date: 2026-03-06 23:50:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9f4d7b2c6a1e"
down_revision: Union[str, Sequence[str], None] = "c1d5e8a2f4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("prediction_binding", "prediction_set_id", new_column_name="prediction_id")
    op.alter_column("prediction_item", "prediction_set_id", new_column_name="prediction_id")


def downgrade() -> None:
    op.alter_column("prediction_item", "prediction_id", new_column_name="prediction_set_id")
    op.alter_column("prediction_binding", "prediction_id", new_column_name="prediction_set_id")
