from __future__ import annotations

from sqlalchemy.sql.sqltypes import DateTime
from sqlmodel import SQLModel

import saki_api.infra.db.models  # noqa: F401  # Ensure SQLModel metadata registration.


def _iter_datetime_columns():
    for table_name, table in SQLModel.metadata.tables.items():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                yield table_name, column


def test_all_datetime_columns_are_timezone_aware() -> None:
    mismatches: list[str] = []
    for table_name, column in _iter_datetime_columns():
        if column.type.timezone is not True:
            mismatches.append(f"{table_name}.{column.name}")

    assert not mismatches, (
        "Found datetime columns without timezone=True: " + ", ".join(sorted(mismatches))
    )


def test_import_task_datetime_columns_are_timezone_aware() -> None:
    import_task = SQLModel.metadata.tables["import_task"]
    import_task_event = SQLModel.metadata.tables["import_task_event"]

    assert import_task.columns["created_at"].type.timezone is True
    assert import_task.columns["updated_at"].type.timezone is True
    assert import_task.columns["started_at"].type.timezone is True
    assert import_task.columns["finished_at"].type.timezone is True
    assert import_task_event.columns["ts"].type.timezone is True
