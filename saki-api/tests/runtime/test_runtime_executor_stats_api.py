from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.modules.runtime.api.http import runtime as runtime_endpoint
from saki_api.modules.runtime.domain.runtime_executor_stats import RuntimeExecutorStats


@pytest.fixture
async def runtime_stats_env(tmp_path):
    db_path = tmp_path / "runtime_executor_stats.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_runtime_executor_stats_bucket_aggregation(runtime_stats_env, monkeypatch):
    session_local = runtime_stats_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(runtime_endpoint, "_ensure_runtime_read_permission", _allow)

    now = datetime.now(UTC)
    anchor_epoch = int((now - timedelta(minutes=10)).timestamp())
    anchor_epoch = anchor_epoch - (anchor_epoch % 20)
    points = [
        datetime.fromtimestamp(anchor_epoch + 1, tz=UTC),
        datetime.fromtimestamp(anchor_epoch + 11, tz=UTC),
        datetime.fromtimestamp(anchor_epoch + 21, tz=UTC),
        datetime.fromtimestamp(anchor_epoch + 31, tz=UTC),
    ]

    async with session_local() as session:
        for idx, ts in enumerate(points, start=1):
            session.add(
                RuntimeExecutorStats(
                    ts=ts,
                    total_count=2,
                    online_count=idx,
                    busy_count=0,
                    available_count=idx,
                    availability_rate=idx / 10.0,
                    pending_assign_count=0,
                    pending_stop_count=0,
                )
            )
        await session.commit()

        response = await runtime_endpoint.get_runtime_executor_stats(
            range="1h",
            session=session,
            current_user_id="test-user",
        )

    assert response.range == "1h"
    assert response.bucket_seconds == 20
    assert len(response.points) == 2
    assert response.points[0].online_count == 2
    assert response.points[1].online_count == 4


@pytest.mark.anyio
async def test_runtime_executor_stats_range_filter(runtime_stats_env, monkeypatch):
    session_local = runtime_stats_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(runtime_endpoint, "_ensure_runtime_read_permission", _allow)

    async with session_local() as session:
        session.add(
            RuntimeExecutorStats(
                ts=datetime.now(UTC) - timedelta(minutes=40),
                total_count=1,
                online_count=1,
                busy_count=0,
                available_count=1,
                availability_rate=1.0,
                pending_assign_count=0,
                pending_stop_count=0,
            )
        )
        session.add(
            RuntimeExecutorStats(
                ts=datetime.now(UTC) - timedelta(minutes=10),
                total_count=3,
                online_count=2,
                busy_count=1,
                available_count=1,
                availability_rate=1 / 3,
                pending_assign_count=0,
                pending_stop_count=0,
            )
        )
        await session.commit()

        response = await runtime_endpoint.get_runtime_executor_stats(
            range="30m",
            session=session,
            current_user_id="test-user",
        )

    assert response.range == "30m"
    assert response.bucket_seconds == 10
    assert len(response.points) == 1
    assert response.points[0].total_count == 3
