"""
Runtime dispatcher for selecting executors and sending control messages.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.runtime_executor import RuntimeExecutor

logger = logging.getLogger(__name__)


@dataclass
class RuntimeSession:
    executor_id: str
    queue: asyncio.Queue[pb.RuntimeMessage]
    version: str
    plugins: set[str] = field(default_factory=set)
    resources: dict[str, Any] = field(default_factory=dict)
    busy: bool = False
    current_job_id: Optional[str] = None
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AssignmentResult:
    request_id: str
    executor_id: str


@dataclass
class PendingAssign:
    request_id: str
    job_id: str
    executor_id: str
    created_at: datetime


class RuntimeDispatcher:
    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeSession] = {}
        self._pending_assign: dict[str, PendingAssign] = {}
        self._pending_stop: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._dispatch_lock = asyncio.Lock()

    async def metrics_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            sessions = list(self._sessions.values())
            pending_assign_items = list(self._pending_assign.values())
            pending_stop_items = list(self._pending_stop.values())

        latest_seen: datetime | None = None
        for session in sessions:
            if latest_seen is None or session.last_seen > latest_seen:
                latest_seen = session.last_seen

        return {
            "session_online_count": len(sessions),
            "session_busy_count": sum(1 for session in sessions if session.busy),
            "pending_assign_count": len(pending_assign_items),
            "pending_stop_count": len(pending_stop_items),
            "latest_session_heartbeat_at": latest_seen,
        }

    async def executor_pending_snapshot(self, executor_id: str, current_job_id: str | None = None) -> dict[str, int]:
        async with self._lock:
            pending_assign_count = sum(
                1
                for pending in self._pending_assign.values()
                if pending.executor_id == executor_id
            )
            pending_stop_count = 0
            if current_job_id:
                pending_stop_count = sum(
                    1 for pending_job_id in self._pending_stop.values() if pending_job_id == current_job_id
                )

        return {
            "pending_assign_count": pending_assign_count,
            "pending_stop_count": pending_stop_count,
        }

    def _clear_pending_for_executor(self, executor_id: str, job_ids: set[str] | None = None) -> None:
        pending_assign_ids = [
            request_id
            for request_id, pending in self._pending_assign.items()
            if pending.executor_id == executor_id
            or (job_ids and pending.job_id in job_ids)
        ]
        for request_id in pending_assign_ids:
            self._pending_assign.pop(request_id, None)

        if job_ids:
            pending_stop_ids = [
                request_id
                for request_id, pending_job_id in self._pending_stop.items()
                if pending_job_id in job_ids
            ]
            for request_id in pending_stop_ids:
                self._pending_stop.pop(request_id, None)

    def _is_executor_allowed(self, executor_id: str) -> bool:
        allowlist = settings.RUNTIME_EXECUTOR_ALLOWLIST
        if not allowlist:
            return True
        return executor_id in allowlist

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _resource_satisfied(self, required: dict[str, Any], available: dict[str, Any]) -> bool:
        req_gpu = self._to_int((required or {}).get("gpu_count"), 0)
        req_mem = self._to_int((required or {}).get("memory_mb"), 0)
        avail_gpu = self._to_int((available or {}).get("gpu_count"), 0)
        avail_mem = self._to_int((available or {}).get("memory_mb"), 0)

        if req_gpu > 0 and avail_gpu < req_gpu:
            return False
        if req_mem > 0 and avail_mem > 0 and avail_mem < req_mem:
            return False
        return True

    @staticmethod
    def _is_retry_ready(job: Job) -> bool:
        params = job.params or {}
        not_before = params.get("_retry_not_before_ts")
        if not_before is None:
            return True
        try:
            return datetime.now(UTC).timestamp() >= float(not_before)
        except Exception:
            return True

    def _build_retry_job(self, failed_job: Job, reason: str) -> Job | None:
        if failed_job.retry_count >= settings.RUNTIME_MAX_RETRY_COUNT:
            return None

        next_retry_count = failed_job.retry_count + 1
        delay_sec = settings.RUNTIME_RETRY_BASE_DELAY_SEC * (2 ** failed_job.retry_count)

        params = dict(failed_job.params or {})
        params["_retry_of"] = str(failed_job.id)
        params["_retry_not_before_ts"] = int(
            (datetime.now(UTC) + timedelta(seconds=delay_sec)).timestamp()
        )

        retry_job = Job(
            project_id=failed_job.project_id,
            loop_id=failed_job.loop_id,
            iteration=failed_job.iteration,
            status=TrainingJobStatus.PENDING,
            job_type=failed_job.job_type,
            plugin_id=failed_job.plugin_id,
            mode=failed_job.mode,
            query_strategy=failed_job.query_strategy,
            params=params,
            resources=dict(failed_job.resources or {}),
            source_commit_id=failed_job.source_commit_id,
            result_commit_id=None,
            assigned_executor_id=None,
            started_at=None,
            ended_at=None,
            retry_count=next_retry_count,
            last_error=f"retry_from:{failed_job.id} reason:{reason}",
            metrics={},
            artifacts={},
        )
        return retry_job

    def _schedule_dispatch(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.dispatch_pending_jobs())

    async def recover_after_api_restart(self) -> dict[str, int]:
        """
        Reconcile runtime state after API process restart.

        - In-memory sessions/pending queues are reset.
        - Persisted executors are marked offline.
        - PENDING jobs with stale assignment are unassigned for redispatch.
        - RUNNING assigned jobs are marked failed and optionally retried.
        """
        async with self._lock:
            self._sessions.clear()
            self._pending_assign.clear()
            self._pending_stop.clear()

        reset_executors = 0
        recovered_pending_assignments = 0
        failed_running_jobs = 0
        created_retry_jobs = 0

        async with SessionLocal() as session:
            executor_rows = await session.exec(select(RuntimeExecutor))
            for executor in executor_rows.all():
                executor.is_online = False
                executor.status = "offline"
                executor.current_job_id = None
                session.add(executor)
                reset_executors += 1

            pending_rows = await session.exec(
                select(Job).where(
                    Job.status == TrainingJobStatus.PENDING,
                    Job.assigned_executor_id.is_not(None),
                )
            )
            for job in pending_rows.all():
                job.assigned_executor_id = None
                job.last_error = "api_restart_recover: assignment cleared"
                session.add(job)
                recovered_pending_assignments += 1

            running_rows = await session.exec(
                select(Job).where(
                    Job.status == TrainingJobStatus.RUNNING,
                    Job.assigned_executor_id.is_not(None),
                )
            )
            for job in running_rows.all():
                job.status = TrainingJobStatus.FAILED
                job.last_error = "runtime_lost: api restarted during running job"
                job.ended_at = datetime.now(UTC)
                job.assigned_executor_id = None
                failed_running_jobs += 1
                session.add(job)

                retry_job = self._build_retry_job(
                    failed_job=job,
                    reason="runtime_lost: api restarted during running job",
                )
                if retry_job is not None:
                    session.add(retry_job)
                    created_retry_jobs += 1

            await session.commit()

        summary = {
            "reset_executors": reset_executors,
            "recovered_pending_assignments": recovered_pending_assignments,
            "failed_running_jobs": failed_running_jobs,
            "created_retry_jobs": created_retry_jobs,
        }
        logger.info(
            "runtime restart recovery completed: %s",
            summary,
        )
        return summary

    async def register(
            self,
            executor_id: str,
            queue: asyncio.Queue[pb.RuntimeMessage],
            version: str,
            plugin_ids: set[str],
            resources: dict[str, Any],
    ) -> None:
        if not self._is_executor_allowed(executor_id):
            raise PermissionError(f"Executor {executor_id} is not in allowlist")

        async with self._lock:
            self._sessions[executor_id] = RuntimeSession(
                executor_id=executor_id,
                queue=queue,
                version=version,
                plugins=plugin_ids,
                resources=resources,
                busy=False,
                current_job_id=None,
                last_seen=datetime.now(UTC),
            )

        async with SessionLocal() as session:
            row = await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
            executor = row.first() or RuntimeExecutor(executor_id=executor_id)
            assert executor is not None
            executor.version = version
            executor.plugin_ids = {"plugins": sorted(plugin_ids)}
            executor.resources = resources
            executor.status = "idle"
            executor.is_online = True
            executor.current_job_id = None
            executor.last_seen_at = datetime.now(UTC)
            session.add(executor)
            await session.commit()

        self._schedule_dispatch()

    async def unregister(self, executor_id: str) -> None:
        removed_session: RuntimeSession | None = None
        async with self._lock:
            removed_session = self._sessions.pop(executor_id, None)

        cleanup_job_ids: set[str] = set()
        if removed_session and removed_session.current_job_id:
            cleanup_job_ids.add(str(removed_session.current_job_id))

        async with SessionLocal() as session:
            row = await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
            executor = row.first()
            if executor:
                executor.is_online = False
                executor.status = "offline"
                executor.current_job_id = None
                session.add(executor)

            running_jobs = await session.exec(
                select(Job).where(
                    Job.assigned_executor_id == executor_id,
                    Job.status.in_([TrainingJobStatus.RUNNING, TrainingJobStatus.PENDING]),
                )
            )
            for job in running_jobs.all():
                cleanup_job_ids.add(str(job.id))
                job.status = TrainingJobStatus.FAILED
                job.last_error = "runtime_lost: stream closed"
                job.ended_at = datetime.now(UTC)
                session.add(job)

                retry_job = self._build_retry_job(failed_job=job, reason="runtime_lost: stream closed")
                if retry_job:
                    session.add(retry_job)
            await session.commit()

        async with self._lock:
            self._clear_pending_for_executor(executor_id, cleanup_job_ids)

        self._schedule_dispatch()

    async def heartbeat(
            self,
            executor_id: str,
            busy: bool,
            current_job_id: str | None,
            resources: dict[str, Any],
    ) -> None:
        async with self._lock:
            session = self._sessions.get(executor_id)
            if session:
                session.last_seen = datetime.now(UTC)
                session.busy = busy
                session.current_job_id = current_job_id
                session.resources = resources or session.resources

        async with SessionLocal() as db:
            row = await db.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
            executor = row.first()
            if executor:
                executor.is_online = True
                executor.status = "busy" if busy else "idle"
                executor.current_job_id = current_job_id
                executor.last_seen_at = datetime.now(UTC)
                executor.resources = resources or executor.resources
                db.add(executor)
                await db.commit()

        if not busy:
            self._schedule_dispatch()

    async def mark_stale_executors(self) -> None:
        now = datetime.now(UTC)
        timeout = timedelta(seconds=settings.RUNTIME_HEARTBEAT_TIMEOUT_SEC)

        async with self._lock:
            stale_ids = [
                executor_id
                for executor_id, session in self._sessions.items()
                if (now - session.last_seen) > timeout
            ]
            for executor_id in stale_ids:
                self._sessions.pop(executor_id, None)

        if not stale_ids:
            return

        stale_job_ids: dict[str, set[str]] = {executor_id: set() for executor_id in stale_ids}
        async with SessionLocal() as session:
            for executor_id in stale_ids:
                row = await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
                executor = row.first()
                if executor:
                    executor.is_online = False
                    executor.status = "offline"
                    executor.current_job_id = None
                    executor.last_error = "heartbeat timeout"
                    session.add(executor)

                running_jobs = await session.exec(
                    select(Job).where(
                        Job.assigned_executor_id == executor_id,
                        Job.status.in_([TrainingJobStatus.RUNNING, TrainingJobStatus.PENDING]),
                    )
                )
                for job in running_jobs.all():
                    stale_job_ids.setdefault(executor_id, set()).add(str(job.id))
                    job.status = TrainingJobStatus.FAILED
                    job.last_error = "runtime_lost: executor heartbeat timeout"
                    job.ended_at = datetime.now(UTC)
                    session.add(job)

                    retry_job = self._build_retry_job(
                        failed_job=job,
                        reason="runtime_lost: executor heartbeat timeout",
                    )
                    if retry_job:
                        session.add(retry_job)
            await session.commit()

        async with self._lock:
            for executor_id in stale_ids:
                self._clear_pending_for_executor(executor_id, stale_job_ids.get(executor_id))

    async def assign_job(self, job: Job, check_stale: bool = True) -> Optional[AssignmentResult]:
        if check_stale:
            await self.mark_stale_executors()

        async with SessionLocal() as session:
            persisted = await session.get(Job, job.id)
            if (
                    (not persisted)
                    or persisted.status != TrainingJobStatus.PENDING
                    or bool(persisted.assigned_executor_id)
            ):
                return None

        async with self._lock:
            job_id = str(job.id)
            if any(pending.job_id == job_id for pending in self._pending_assign.values()):
                return None
            if any(runtime_session.current_job_id == job_id for runtime_session in self._sessions.values()):
                return None
            candidates = [
                s for s in self._sessions.values()
                if (not s.busy)
                and ((not job.plugin_id) or (job.plugin_id in s.plugins))
                and self._resource_satisfied(job.resources or {}, s.resources or {})
            ]
            if not candidates:
                return None

            target = sorted(candidates, key=lambda item: item.last_seen)[0]
            request_id = str(uuid.uuid4())
            target.busy = True
            target.current_job_id = job_id
            self._pending_assign[request_id] = PendingAssign(
                request_id=request_id,
                job_id=job_id,
                executor_id=target.executor_id,
                created_at=datetime.now(UTC),
            )

            await target.queue.put(
                pb.RuntimeMessage(
                    assign_job=pb.AssignJob(
                        request_id=request_id,
                        job=pb.JobPayload(
                            job_id=job_id,
                            project_id=str(job.project_id),
                            loop_id=str(job.loop_id),
                            source_commit_id=str(job.source_commit_id),
                            job_type=runtime_codec.text_to_job_type(job.job_type),
                            plugin_id=job.plugin_id or "",
                            mode=runtime_codec.text_to_job_mode(job.mode),
                            query_strategy=job.query_strategy or "",
                            params=runtime_codec.dict_to_struct(job.params or {}),
                            resources=runtime_codec.dict_to_resource_summary(job.resources or {}),
                            iteration=int(job.iteration or 0),
                        ),
                    )
                )
            )
            target.last_seen = datetime.now(UTC)

        async with SessionLocal() as session:
            row = await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == target.executor_id))
            executor = row.first()
            if executor:
                executor.status = "reserved"
                executor.current_job_id = str(job.id)
                executor.is_online = True
                executor.last_seen_at = datetime.now(UTC)
                session.add(executor)

            persisted_job = await session.get(Job, job.id)
            if (
                    persisted_job
                    and persisted_job.status == TrainingJobStatus.PENDING
                    and not persisted_job.assigned_executor_id
            ):
                persisted_job.assigned_executor_id = target.executor_id
                session.add(persisted_job)
            await session.commit()

        return AssignmentResult(request_id=request_id, executor_id=target.executor_id)

    async def stop_job(self, job_id: str, reason: str) -> tuple[str, bool]:
        async with self._lock:
            for pending_request_id, pending_job_id in self._pending_stop.items():
                if pending_job_id == job_id:
                    return pending_request_id, True

            target = None
            for session in self._sessions.values():
                if session.current_job_id == job_id:
                    target = session
                    break
            if target:
                request_id = str(uuid.uuid4())
                await target.queue.put(
                    pb.RuntimeMessage(
                        stop_job=pb.StopJob(
                            request_id=request_id,
                            job_id=job_id,
                            reason=reason,
                        )
                    )
                )
                self._pending_stop[request_id] = job_id
                return request_id, True

        return str(uuid.uuid4()), False

    async def send_data_response(self, executor_id: str, response_payload: pb.RuntimeMessage) -> None:
        async with self._lock:
            session = self._sessions.get(executor_id)
            if session:
                await session.queue.put(response_payload)

    async def send_upload_ticket_response(self, executor_id: str, response_payload: pb.RuntimeMessage) -> None:
        await self.send_data_response(executor_id, response_payload)

    async def handle_ack(self, ack_for: str, status: int, message: str | None = None) -> None:
        is_ok = status == pb.OK

        if ack_for in self._pending_assign:
            pending = self._pending_assign.pop(ack_for)
            job_id = pending.job_id
            release_executor_id: str | None = None
            async with self._lock:
                for runtime_session in self._sessions.values():
                    if runtime_session.executor_id == pending.executor_id and runtime_session.current_job_id == job_id:
                        if not is_ok:
                            runtime_session.busy = False
                            runtime_session.current_job_id = None
                        release_executor_id = runtime_session.executor_id
                        break

            async with SessionLocal() as session:
                job = await session.get(Job, uuid.UUID(job_id))
                if job:
                    if is_ok:
                        job.status = TrainingJobStatus.RUNNING
                        if not job.started_at:
                            job.started_at = datetime.now(UTC)
                    else:
                        job.status = TrainingJobStatus.FAILED
                        job.last_error = message or "executor reject assignment"
                        job.ended_at = datetime.now(UTC)
                        job.assigned_executor_id = None
                    session.add(job)
                    if release_executor_id:
                        row = await session.exec(
                            select(RuntimeExecutor).where(RuntimeExecutor.executor_id == release_executor_id)
                        )
                        executor = row.first()
                        if executor:
                            if is_ok:
                                executor.status = "busy"
                                executor.current_job_id = job_id
                            else:
                                executor.status = "idle"
                                executor.current_job_id = None
                            executor.is_online = True
                            executor.last_seen_at = datetime.now(UTC)
                            session.add(executor)
                    await session.commit()

        if ack_for in self._pending_stop:
            self._pending_stop.pop(ack_for, None)

    async def reap_assign_timeouts(self) -> None:
        timeout_sec = max(1, int(settings.RUNTIME_ASSIGN_ACK_TIMEOUT_SEC))
        now = datetime.now(UTC)
        timeout = timedelta(seconds=timeout_sec)

        timed_out: list[PendingAssign] = []
        async with self._lock:
            for request_id, pending in list(self._pending_assign.items()):
                if now - pending.created_at >= timeout:
                    timed_out.append(pending)
                    self._pending_assign.pop(request_id, None)
                    runtime_session = self._sessions.get(pending.executor_id)
                    if runtime_session and runtime_session.current_job_id == pending.job_id:
                        runtime_session.busy = False
                        runtime_session.current_job_id = None

        if not timed_out:
            return

        timed_out_job_ids = {pending.job_id for pending in timed_out}
        pending_stop_to_remove: list[str] = []
        async with SessionLocal() as session:
            for pending in timed_out:
                try:
                    job_uuid = uuid.UUID(pending.job_id)
                except Exception:
                    continue

                job = await session.get(Job, job_uuid)
                if job and job.status == TrainingJobStatus.PENDING:
                    job.assigned_executor_id = None
                    job.last_error = f"assign_ack_timeout executor={pending.executor_id}"
                    session.add(job)

                row = await session.exec(
                    select(RuntimeExecutor).where(RuntimeExecutor.executor_id == pending.executor_id)
                )
                executor = row.first()
                if executor and executor.current_job_id == pending.job_id:
                    executor.status = "idle"
                    executor.current_job_id = None
                    executor.is_online = True
                    executor.last_error = f"assign_ack_timeout job={pending.job_id}"
                    executor.last_seen_at = datetime.now(UTC)
                    session.add(executor)

            for request_id, pending_job_id in list(self._pending_stop.items()):
                if pending_job_id in timed_out_job_ids:
                    pending_stop_to_remove.append(request_id)

            await session.commit()

        if pending_stop_to_remove:
            async with self._lock:
                for request_id in pending_stop_to_remove:
                    self._pending_stop.pop(request_id, None)

        self._schedule_dispatch()

    async def mark_executor_idle(self, executor_id: str, job_id: str | None = None) -> None:
        async with self._lock:
            session = self._sessions.get(executor_id)
            if session:
                session.busy = False
                if job_id is None or session.current_job_id == job_id:
                    session.current_job_id = None
                session.last_seen = datetime.now(UTC)

        async with SessionLocal() as db:
            row = await db.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == executor_id))
            executor = row.first()
            if executor:
                executor.status = "idle"
                executor.current_job_id = None
                executor.is_online = True
                executor.last_seen_at = datetime.now(UTC)
                db.add(executor)
                await db.commit()

        self._schedule_dispatch()

    async def dispatch_pending_jobs(self) -> None:
        if self._dispatch_lock.locked():
            return

        async with self._dispatch_lock:
            await self.reap_assign_timeouts()
            await self.mark_stale_executors()
            while True:
                async with SessionLocal() as session:
                    rows = await session.exec(
                        select(Job)
                        .where(Job.status == TrainingJobStatus.PENDING)
                        .order_by(Job.created_at.asc())
                        .limit(100)
                    )
                    pending_jobs = list(rows.all())

                if not pending_jobs:
                    break

                dispatched_any = False
                for job in pending_jobs:
                    if job.assigned_executor_id:
                        continue
                    if not self._is_retry_ready(job):
                        continue
                    assigned = await self.assign_job(job, check_stale=False)
                    if assigned:
                        dispatched_any = True

                if not dispatched_any:
                    break


runtime_dispatcher = RuntimeDispatcher()
