from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
import saki_api.grpc.dispatcher as dispatcher_module
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus, ALLoopMode
from saki_api.models.l3.job import Job


class _LogCapture:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, message: str, *args) -> None:
        try:
            rendered = message.format(*args)
        except Exception:
            rendered = f"{message} | args={args}"
        self.records.append((level, rendered))

    def info(self, message: str, *args) -> None:
        self._add("INFO", message, *args)

    def warning(self, message: str, *args) -> None:
        self._add("WARNING", message, *args)

    def error(self, message: str, *args) -> None:
        self._add("ERROR", message, *args)

    def exception(self, message: str, *args) -> None:
        self._add("EXCEPTION", message, *args)

    def has(self, keyword: str) -> bool:
        return any(keyword in text for _, text in self.records)


@pytest.fixture
async def dispatcher_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_dispatcher_logging.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(dispatcher_module, "SessionLocal", session_local)
    monkeypatch.setattr(dispatcher_module.settings, "RUNTIME_EXECUTOR_ALLOWLIST", [])
    dispatcher = dispatcher_module.RuntimeDispatcher()
    dispatcher._schedule_dispatch = lambda: None  # type: ignore[assignment]
    try:
        yield dispatcher, session_local
    finally:
        await engine.dispose()


async def _create_pending_job(session_local: async_sessionmaker[AsyncSession]) -> Job:
    job = Job(
        project_id=uuid.uuid4(),
        loop_id=uuid.uuid4(),
        round_index=1,
        status=TrainingJobStatus.PENDING,
        job_type="train_detection",
        plugin_id="demo_det_v1",
        mode=ALLoopMode.ACTIVE_LEARNING,
        query_strategy="uncertainty_1_minus_max_conf",
        params={},
        resources={"gpu_count": 1, "memory_mb": 0},
        source_commit_id=uuid.uuid4(),
    )
    async with session_local() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


@pytest.mark.anyio
async def test_runtime_logging_register_and_unregister(dispatcher_env, monkeypatch):
    dispatcher, _ = dispatcher_env
    capture = _LogCapture()
    monkeypatch.setattr(dispatcher_module, "logger", capture)

    queue: asyncio.Queue = asyncio.Queue()
    await dispatcher.register(
        executor_id="executor-log-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 8192},
    )
    await dispatcher.unregister("executor-log-1")

    assert capture.has("执行器已连接")
    assert capture.has("执行器已断开")


@pytest.mark.anyio
async def test_runtime_logging_assign_and_ack_success(dispatcher_env, monkeypatch):
    dispatcher, session_local = dispatcher_env
    capture = _LogCapture()
    monkeypatch.setattr(dispatcher_module, "logger", capture)

    queue: asyncio.Queue = asyncio.Queue()
    job = await _create_pending_job(session_local)
    await dispatcher.register(
        executor_id="executor-log-2",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 8192},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    _ = await asyncio.wait_for(queue.get(), timeout=1)

    await dispatcher.handle_ack(
        ack_for=assigned.request_id,
        status=pb.OK,
        ack_type=pb.ACK_TYPE_ASSIGN_JOB,
        ack_reason=pb.ACK_REASON_ACCEPTED,
        detail="accepted",
    )

    assert capture.has("任务已派发，等待 ACK")
    assert capture.has("任务已开始执行（ACK 成功）")


@pytest.mark.anyio
async def test_runtime_logging_assign_ack_timeout(dispatcher_env, monkeypatch):
    dispatcher, session_local = dispatcher_env
    capture = _LogCapture()
    monkeypatch.setattr(dispatcher_module, "logger", capture)
    monkeypatch.setattr(dispatcher_module.settings, "RUNTIME_ASSIGN_ACK_TIMEOUT_SEC", 1)

    queue: asyncio.Queue = asyncio.Queue()
    job = await _create_pending_job(session_local)
    await dispatcher.register(
        executor_id="executor-log-3",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 8192},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None

    pending = dispatcher._pending_assign.get(assigned.request_id)  # noqa: SLF001
    assert pending is not None
    pending.created_at = datetime.now(UTC) - timedelta(seconds=5)

    await dispatcher.reap_assign_timeouts()

    assert capture.has("任务派发等待 ACK 超时")
