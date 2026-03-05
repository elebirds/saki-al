from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.modules.runtime.domain.runtime_executor import RuntimeExecutor
from saki_api.modules.runtime.service.observability.runtime_observability_service import RuntimeObservabilityService


class _FailingDispatcherAdminClient:
    enabled = True

    async def get_runtime_summary(self):
        raise RuntimeError("dispatcher unavailable")

    async def list_executors(self):
        raise RuntimeError("dispatcher unavailable")

    async def get_executor(self, executor_id: str):
        del executor_id
        raise RuntimeError("dispatcher unavailable")


@pytest.fixture
async def runtime_observability_env(tmp_path):
    db_path = tmp_path / "runtime_observability_fallback.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_list_executors_falls_back_to_registry_counts_when_dispatcher_unavailable(runtime_observability_env):
    session_local = runtime_observability_env
    now = datetime.now(UTC)

    async with session_local() as session:
        session.add(
            RuntimeExecutor(
                executor_id="exec-1",
                version="v1",
                status="idle",
                is_online=True,
                last_seen_at=now - timedelta(seconds=30),
            )
        )
        session.add(
            RuntimeExecutor(
                executor_id="exec-2",
                version="v1",
                status="busy",
                is_online=True,
                last_seen_at=now - timedelta(seconds=15),
            )
        )
        session.add(
            RuntimeExecutor(
                executor_id="exec-3",
                version="v1",
                status="offline",
                is_online=False,
                last_seen_at=now - timedelta(minutes=2),
            )
        )
        await session.commit()

        service = RuntimeObservabilityService(
            session=session,
            dispatcher_admin_client=_FailingDispatcherAdminClient(),
        )
        response = await service.list_executors()

        assert response.summary.total_count == 3
        assert response.summary.online_count == 2
        assert response.summary.busy_count == 1
        assert response.summary.available_count == 1
        assert response.summary.pending_assign_count == 0
        assert response.summary.pending_stop_count == 0
        assert len(response.items) == 3
        assert all(item.pending_assign_count == 0 for item in response.items)
        assert all(item.pending_stop_count == 0 for item in response.items)

        executor = await service.get_executor("exec-1")
        assert executor.pending_assign_count == 0
        assert executor.pending_stop_count == 0
