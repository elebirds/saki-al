"""label_sort_order_constraints

Revision ID: 1c3a6d7e9f20
Revises: f2b4c8d1e7a9
Create Date: 2026-03-02 05:10:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c3a6d7e9f20"
down_revision = "f2b4c8d1e7a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 先把历史数据压实为 1..N，保证后续唯一与正数约束可创建。
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, project_id, sort_order, created_at
                FROM label
                ORDER BY
                    project_id,
                    CASE WHEN sort_order > 0 THEN sort_order ELSE 2147483647 END,
                    created_at,
                    id
                """
            )
        )
    )

    current_project_id = None
    position = 0
    for row in rows:
        project_id = row[1]
        if project_id != current_project_id:
            current_project_id = project_id
            position = 1
        else:
            position += 1
        bind.execute(
            sa.text("UPDATE label SET sort_order = :sort_order WHERE id = :label_id"),
            {
                "sort_order": int(position),
                "label_id": row[0],
            },
        )

    op.create_unique_constraint(
        "uq_project_label_sort_order",
        "label",
        ["project_id", "sort_order"],
    )
    op.create_check_constraint(
        "ck_label_sort_order_positive",
        "label",
        "sort_order > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_label_sort_order_positive", "label", type_="check")
    op.drop_constraint("uq_project_label_sort_order", "label", type_="unique")
