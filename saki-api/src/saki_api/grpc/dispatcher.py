"""Runtime dispatcher for Task-based assignment."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from loguru import logger
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import JobStatusV2, JobTaskStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_task import JobTask
from saki_api.models.l3.runtime_executor import RuntimeExecutor


@dataclass
class RuntimeSession:
    executor_id: str
    queue: asyncio.Queue[pb.RuntimeMessage]
    version: str
    plugins: set[str] = field(default_factory=set)
    plugin_payloads: list[dict[str, Any]] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    busy: bool = False
    current_task_id: Optional[str] = None
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PendingAssign:
    request_id: str
    task_id: str
    executor_id: str
    created_at: datetime


class RuntimeDispatcher:
    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeSession] = {}
        self._pending_assign: dict[str, PendingAssign] = {}
        self._pending_stop: dict[str, str] = {}
        self._task_queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._queued_task_ids: set[uuid.UUID] = set()
        self._lock = asyncio.Lock()
        self._dispatch_lock = asyncio.Lock()

    async def register_executor(
        self,
        *,
        executor_id: str,
        version: str,
        plugin_payloads: list[dict[str, Any]],
        resources: dict[str, Any],
    ) -> RuntimeSession:
        plugins = {
            str(item.get("plugin_id") or "").strip()
            for item in (plugin_payloads or [])
            if str(item.get("plugin_id") or "").strip()
        }
        async with self._lock:
            queue: asyncio.Queue[pb.RuntimeMessage]
            existing = self._sessions.get(executor_id)
            if existing:
                queue = existing.queue
            else:
                queue = asyncio.Queue()
            session = RuntimeSession(
                executor_id=executor_id,
                queue=queue,
                version=version,
                plugins=set(plugins),
                plugin_payloads=[dict(item) for item in (plugin_payloads or []) if isinstance(item, dict)],
                resources=dict(resources or {}),
                busy=False,
                current_task_id=None,
                last_seen=datetime.now(UTC),
            )
            self._sessions[executor_id] = session

        await self._upsert_executor_row(session)
        logger.info("runtime executor registered executor_id={} plugins={}", executor_id, sorted(plugins))
        return session

    async def unregister_executor(self, executor_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(executor_id, None)
            affected_task_ids = [pending.task_id for pending in self._pending_assign.values() if pending.executor_id == executor_id]
            pending_keys = [request_id for request_id, pending in self._pending_assign.items() if pending.executor_id == executor_id]
            for key in pending_keys:
                self._pending_assign.pop(key, None)
        if session:
            logger.info("runtime executor disconnected executor_id={}", executor_id)
        for task_id in affected_task_ids:
            await self._reset_task_to_pending(uuid.UUID(task_id), reason="executor disconnected")

        async with SessionLocal() as session_db:
            executor = (
                await session_db.exec(
                    select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id).limit(1)
                )
            ).first()
            if executor:
                executor.is_online = False
                executor.status = "offline"
                executor.current_task_id = None
                executor.last_seen_at = datetime.now(UTC)
                session_db.add(executor)
                await session_db.commit()

    async def metrics_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            sessions = list(self._sessions.values())
            pending_assign_count = len(self._pending_assign)
            pending_stop_count = len(self._pending_stop)
            queued_count = len(self._queued_task_ids)

        latest_seen = max([s.last_seen for s in sessions], default=None)
        return {
            "session_online_count": len(sessions),
            "session_busy_count": sum(1 for s in sessions if s.busy),
            "pending_assign_count": pending_assign_count,
            "pending_stop_count": pending_stop_count,
            "queued_task_count": queued_count,
            "latest_session_heartbeat_at": latest_seen,
        }

    async def executor_pending_snapshot(self, executor_id: str, current_task_id: str | None = None) -> dict[str, int]:
        async with self._lock:
            pending_assign_count = sum(
                1 for pending in self._pending_assign.values() if pending.executor_id == executor_id
            )
            pending_stop_count = 0
            if current_task_id:
                pending_stop_count = sum(
                    1 for pending_task_id in self._pending_stop.values() if pending_task_id == current_task_id
                )
        return {
            "pending_assign_count": pending_assign_count,
            "pending_stop_count": pending_stop_count,
        }

    async def enqueue_task(self, task_id: uuid.UUID) -> None:
        async with self._lock:
            if task_id in self._queued_task_ids:
                return
            self._queued_task_ids.add(task_id)
            await self._task_queue.put(task_id)

    async def assign_task(self, task_id: uuid.UUID) -> bool:
        async with self._dispatch_lock:
            await self._cleanup_stale_assignments()
            return await self._assign_task_locked(task_id)

    async def dispatch_pending_tasks(self) -> None:
        async with self._dispatch_lock:
            await self._cleanup_stale_assignments()
            while not self._task_queue.empty():
                task_id = await self._task_queue.get()
                async with self._lock:
                    self._queued_task_ids.discard(task_id)
                assigned = await self._assign_task_locked(task_id)
                if not assigned:
                    break

    async def _assign_task_locked(self, task_id: uuid.UUID) -> bool:
        task_payload = await self._load_task_payload(task_id)
        if not task_payload:
            return False

        executor = await self._pick_executor(task_payload["plugin_id"])
        if not executor:
            await self.enqueue_task(task_id)
            return False

        request_id = str(uuid.uuid4())
        assign_message = runtime_codec.build_assign_task_message(
            request_id=request_id,
            payload=task_payload,
        )

        async with SessionLocal() as session_db:
            task = await session_db.get(JobTask, task_id)
            if not task or task.status != JobTaskStatus.PENDING:
                return False
            task.status = JobTaskStatus.DISPATCHING
            task.assigned_executor_id = executor.executor_id
            session_db.add(task)

            job = await session_db.get(Job, task.job_id)
            if job and job.summary_status == JobStatusV2.JOB_PENDING:
                job.summary_status = JobStatusV2.JOB_RUNNING
                session_db.add(job)

            await session_db.commit()

        async with self._lock:
            session = self._sessions.get(executor.executor_id)
            if not session:
                await self._reset_task_to_pending(task_id, reason="executor session gone")
                return False
            self._pending_assign[request_id] = PendingAssign(
                request_id=request_id,
                task_id=str(task_id),
                executor_id=executor.executor_id,
                created_at=datetime.now(UTC),
            )
            session.busy = True
            session.current_task_id = str(task_id)
            await session.queue.put(assign_message)

        logger.info("task assigned task_id={} executor_id={} request_id={}", task_id, executor.executor_id, request_id)
        return True

    async def _pick_executor(self, plugin_id: str) -> RuntimeSession | None:
        allowlist = set(settings.RUNTIME_EXECUTOR_ALLOWLIST or [])
        async with self._lock:
            candidates = []
            for session in self._sessions.values():
                if allowlist and session.executor_id not in allowlist:
                    continue
                if session.busy:
                    continue
                if plugin_id and session.plugins and plugin_id not in session.plugins:
                    continue
                candidates.append(session)
            candidates.sort(key=lambda item: item.last_seen, reverse=True)
            return candidates[0] if candidates else None

    async def _load_task_payload(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        async with SessionLocal() as session_db:
            task = await session_db.get(JobTask, task_id)
            if not task:
                return None
            if task.status not in {JobTaskStatus.PENDING, JobTaskStatus.DISPATCHING, JobTaskStatus.RETRYING}:
                return None
            job = await session_db.get(Job, task.job_id)
            if not job:
                return None

            payload = {
                "task_id": str(task.id),
                "job_id": str(job.id),
                "loop_id": str(job.loop_id),
                "project_id": str(job.project_id),
                "source_commit_id": str(task.source_commit_id or job.source_commit_id or ""),
                "task_type": task.task_type.value,
                "plugin_id": job.plugin_id,
                "mode": job.mode.value,
                "query_strategy": job.query_strategy,
                "params": dict(task.params or job.params or {}),
                "resources": dict(job.resources or {}),
                "round_index": int(job.round_index),
                "attempt": int(task.attempt),
                "depends_on_task_ids": list(task.depends_on or []),
            }
            return payload

    async def _cleanup_stale_assignments(self) -> None:
        timeout_sec = max(5, int(settings.RUNTIME_ASSIGN_ACK_TIMEOUT_SEC))
        now = datetime.now(UTC)
        stale: list[PendingAssign] = []
        async with self._lock:
            for request_id, pending in list(self._pending_assign.items()):
                if (now - pending.created_at).total_seconds() > timeout_sec:
                    stale.append(pending)
                    self._pending_assign.pop(request_id, None)
                    session = self._sessions.get(pending.executor_id)
                    if session and session.current_task_id == pending.task_id:
                        session.busy = False
                        session.current_task_id = None

        for pending in stale:
            await self._reset_task_to_pending(uuid.UUID(pending.task_id), reason="assign ack timeout")
            await self.enqueue_task(uuid.UUID(pending.task_id))
            logger.warning("task assign ack timeout task_id={} executor_id={}", pending.task_id, pending.executor_id)

    async def handle_heartbeat(
        self,
        *,
        executor_id: str,
        busy: bool,
        current_task_id: str | None,
        resources: dict[str, Any],
    ) -> None:
        async with self._lock:
            session = self._sessions.get(executor_id)
            if not session:
                return
            session.busy = bool(busy)
            session.current_task_id = str(current_task_id or "") or None
            session.resources = dict(resources or {})
            session.last_seen = datetime.now(UTC)

        async with SessionLocal() as session_db:
            executor = (
                await session_db.exec(
                    select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id).limit(1)
                )
            ).first()
            if executor:
                executor.status = "busy" if busy else "idle"
                executor.current_task_id = current_task_id
                executor.resources = resources or {}
                executor.last_seen_at = datetime.now(UTC)
                executor.is_online = True
                session_db.add(executor)
                await session_db.commit()

    async def handle_ack(self, ack: pb.Ack) -> None:
        ack_type = int(ack.type)
        ok = int(ack.status) == pb.OK
        ack_for = str(ack.ack_for or "")

        if ack_type == pb.ACK_TYPE_ASSIGN_TASK:
            pending = None
            async with self._lock:
                pending = self._pending_assign.pop(ack_for, None)
            if not pending:
                return

            task_id = uuid.UUID(pending.task_id)
            if ok:
                await self._mark_task_running(task_id=task_id, executor_id=pending.executor_id)
            else:
                await self._reset_task_to_pending(task_id, reason=str(ack.detail or "assign rejected"))
                async with self._lock:
                    session = self._sessions.get(pending.executor_id)
                    if session and session.current_task_id == pending.task_id:
                        session.busy = False
                        session.current_task_id = None
                await self.enqueue_task(task_id)
            return

        if ack_type == pb.ACK_TYPE_STOP_TASK:
            pending_task_id = None
            async with self._lock:
                pending_task_id = self._pending_stop.pop(ack_for, None)
            if not pending_task_id:
                return
            if not ok:
                logger.warning("stop task rejected task_id={} detail={}", pending_task_id, ack.detail)

    async def stop_task(self, task_id: str, reason: str) -> tuple[str, bool]:
        request_id = str(uuid.uuid4())
        async with SessionLocal() as session_db:
            task_uuid = uuid.UUID(task_id)
            task = await session_db.get(JobTask, task_uuid)
            if not task:
                raise ValueError(f"task not found: {task_id}")

            if task.status in {
                JobTaskStatus.SUCCEEDED,
                JobTaskStatus.FAILED,
                JobTaskStatus.CANCELLED,
                JobTaskStatus.SKIPPED,
            }:
                return request_id, False

            executor_id = task.assigned_executor_id
            if not executor_id:
                task.status = JobTaskStatus.CANCELLED
                task.last_error = reason
                session_db.add(task)
                await session_db.commit()
                return request_id, False

            stop_message = runtime_codec.build_stop_task_message(
                request_id=request_id,
                task_id=task_id,
                reason=reason,
            )

        async with self._lock:
            session = self._sessions.get(executor_id)
            if not session:
                await self._reset_task_to_pending(uuid.UUID(task_id), reason="executor offline while stop")
                return request_id, False
            self._pending_stop[request_id] = task_id
            await session.queue.put(stop_message)

        return request_id, True

    async def _mark_task_running(self, *, task_id: uuid.UUID, executor_id: str) -> None:
        async with SessionLocal() as session_db:
            task = await session_db.get(JobTask, task_id)
            if not task:
                return
            task.status = JobTaskStatus.RUNNING
            task.assigned_executor_id = executor_id
            if not task.started_at:
                task.started_at = datetime.now(UTC)
            session_db.add(task)

            job = await session_db.get(Job, task.job_id)
            if job:
                job.summary_status = JobStatusV2.JOB_RUNNING
                session_db.add(job)

            await session_db.commit()

    async def _reset_task_to_pending(self, task_id: uuid.UUID, reason: str) -> None:
        async with SessionLocal() as session_db:
            task = await session_db.get(JobTask, task_id)
            if not task:
                return
            if task.status in {
                JobTaskStatus.SUCCEEDED,
                JobTaskStatus.FAILED,
                JobTaskStatus.CANCELLED,
                JobTaskStatus.SKIPPED,
            }:
                return
            task.status = JobTaskStatus.PENDING
            task.assigned_executor_id = None
            task.last_error = reason
            session_db.add(task)
            await session_db.commit()

    async def _upsert_executor_row(self, session: RuntimeSession) -> None:
        async with SessionLocal() as session_db:
            row = (
                await session_db.exec(
                    select(RuntimeExecutor).where(RuntimeExecutor.executor_id == session.executor_id).limit(1)
                )
            ).first()
            now = datetime.now(UTC)
            if row is None:
                row = RuntimeExecutor(
                    executor_id=session.executor_id,
                    version=session.version,
                    status="idle",
                    plugin_ids={"plugins": session.plugin_payloads},
                    resources=session.resources,
                    current_task_id=None,
                    is_online=True,
                    last_seen_at=now,
                )
            else:
                row.version = session.version
                row.status = "idle"
                row.plugin_ids = {"plugins": session.plugin_payloads}
                row.resources = session.resources
                row.current_task_id = None
                row.is_online = True
                row.last_seen_at = now
            session_db.add(row)
            await session_db.commit()

    async def get_outgoing(self, executor_id: str, timeout: float = 1.0) -> Optional[pb.RuntimeMessage]:
        async with self._lock:
            session = self._sessions.get(executor_id)
            if not session:
                return None
            queue = session.queue
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


runtime_dispatcher = RuntimeDispatcher()
