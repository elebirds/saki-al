from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from saki_api.modules.runtime.repo.al_loop_visibility import ALLoopVisibilityRepository
from saki_api.modules.shared.modeling.enums import VisibilitySource


def _mock_session(*, dialect_name: str) -> tuple[SimpleNamespace, AsyncMock, AsyncMock]:
    exec_mock = AsyncMock()
    flush_mock = AsyncMock()
    session = SimpleNamespace(
        exec=exec_mock,
        flush=flush_mock,
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect_name)),
    )
    return session, exec_mock, flush_mock


def _build_rows(repo: ALLoopVisibilityRepository, *, count: int) -> list[dict]:
    loop_id = uuid.uuid4()
    return [
        repo.build_row(
            loop_id=loop_id,
            sample_id=uuid.uuid4(),
            visible_in_train=False,
            source=VisibilitySource.SNAPSHOT_INIT,
            revealed_round_index=None,
            reveal_commit_id=None,
        )
        for _ in range(count)
    ]


@pytest.mark.anyio
async def test_upsert_rows_batches_when_postgres_bind_params_would_overflow() -> None:
    session, exec_mock, flush_mock = _mock_session(dialect_name="postgresql")
    repo = ALLoopVisibilityRepository(session)  # type: ignore[arg-type]
    repo._POSTGRES_MAX_BIND_PARAMS = 16
    rows = _build_rows(repo, count=5)

    await repo.upsert_rows(rows)

    # Each row has 8 fields, so 16 bind params means at most 2 rows per statement.
    assert exec_mock.await_count == 3
    flush_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_upsert_rows_keeps_single_statement_for_non_postgres() -> None:
    session, exec_mock, flush_mock = _mock_session(dialect_name="sqlite")
    repo = ALLoopVisibilityRepository(session)  # type: ignore[arg-type]
    repo._POSTGRES_MAX_BIND_PARAMS = 16
    rows = _build_rows(repo, count=5)

    await repo.upsert_rows(rows)

    assert exec_mock.await_count == 1
    flush_mock.assert_awaited_once()
