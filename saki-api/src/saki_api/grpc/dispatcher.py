"""
Runtime dispatcher for selecting executors and sending control messages.
"""

from __future__ import annotations

import asyncio
from loguru import logger
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, inspect
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.models.l3.runtime_executor_stats import RuntimeExecutorStats



@dataclass
class RuntimeSession:
    executor_id: str
    queue: asyncio.Queue[pb.RuntimeMessage]
    version: str
    plugins: set[str] = field(default_factory=set)
    plugin_capabilities: dict[str, dict[str, Any]] = field(default_factory=dict)
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
        self._stats_lock = asyncio.Lock()
        self._stats_last_persist_at: datetime | None = None
        self._stats_last_cleanup_at: datetime | None = None
        self._stats_persist_interval = timedelta(seconds=10)
        self._stats_retention = timedelta(days=7)
        self._stats_cleanup_interval = timedelta(minutes=10)

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

    @staticmethod
    def _required_stats_tables() -> tuple[str, ...]:
        return (
            RuntimeExecutor.__tablename__,
            RuntimeExecutorStats.__tablename__,
        )

    async def _has_required_stats_tables(self, session) -> bool:
        required_tables = self._required_stats_tables()
        connection = await session.connection()

        def _check(sync_conn) -> bool:
            table_inspector = inspect(sync_conn)
            return all(table_inspector.has_table(table_name) for table_name in required_tables)

        return await connection.run_sync(_check)

    async def _persist_runtime_stats(self, force: bool = False) -> None:
        now = datetime.now(UTC)
        if not force and self._stats_last_persist_at and (now - self._stats_last_persist_at) < self._stats_persist_interval:
            return

        async with self._stats_lock:
            now = datetime.now(UTC)
            if (
                    not force
                    and self._stats_last_persist_at
                    and (now - self._stats_last_persist_at) < self._stats_persist_interval
            ):
                return

            async with self._lock:
                pending_assign_count = len(self._pending_assign)
                pending_stop_count = len(self._pending_stop)

            async with SessionLocal() as session:
                if not await self._has_required_stats_tables(session):
                    return

                rows = await session.exec(select(RuntimeExecutor))
                executors = list(rows.all())
                total_count = len(executors)
                online_count = sum(1 for executor in executors if executor.is_online)
                busy_count = sum(1 for executor in executors if executor.status in {"busy", "reserved"})
                available_count = sum(
                    1
                    for executor in executors
                    if executor.is_online and executor.status not in {"busy", "reserved", "offline"}
                )
                availability_rate = (available_count / total_count) if total_count > 0 else 0.0

                session.add(
                    RuntimeExecutorStats(
                        ts=now,
                        total_count=total_count,
                        online_count=online_count,
                        busy_count=busy_count,
                        available_count=available_count,
                        availability_rate=availability_rate,
                        pending_assign_count=pending_assign_count,
                        pending_stop_count=pending_stop_count,
                    )
                )

                cleanup_due = (
                    self._stats_last_cleanup_at is None
                    or (now - self._stats_last_cleanup_at) >= self._stats_cleanup_interval
                )
                if cleanup_due:
                    cutoff = now - self._stats_retention
                    await session.exec(
                        delete(RuntimeExecutorStats).where(RuntimeExecutorStats.ts < cutoff)
                    )
                    self._stats_last_cleanup_at = now

                await session.commit()

            self._stats_last_persist_at = now

    async def _try_persist_runtime_stats(self, force: bool = False) -> None:
        try:
            await self._persist_runtime_stats(force=force)
        except Exception as exc:
            logger.warning("写入 runtime 统计快照失败 error={}", exc)

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

    @staticmethod
    def _normalize_plugin_capabilities(
            plugin_ids: set[str],
            plugin_capabilities: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for item in plugin_capabilities or []:
            if not isinstance(item, dict):
                continue
            plugin_id = str(item.get("plugin_id") or "").strip()
            if not plugin_id:
                continue
            supported_accelerators = sorted(
                {
                    str(v).strip().lower()
                    for v in (item.get("supported_accelerators") or [])
                    if str(v).strip().lower() in {"cpu", "cuda", "mps"}
                }
            )
            supports_auto_fallback = bool(item.get("supports_auto_fallback"))
            if "supports_auto_fallback" not in item:
                supports_auto_fallback = True
            if "supports_auto_fallback" in item and not supports_auto_fallback and not supported_accelerators:
                supports_auto_fallback = True
            by_id[plugin_id] = {
                "plugin_id": plugin_id,
                "display_name": str(item.get("display_name") or plugin_id),
                "version": str(item.get("version") or ""),
                "supported_job_types": sorted({str(v) for v in (item.get("supported_job_types") or []) if str(v)}),
                "supported_strategies": sorted({str(v) for v in (item.get("supported_strategies") or []) if str(v)}),
                "request_config_schema": dict(item.get("request_config_schema") or {}),
                "default_request_config": dict(item.get("default_request_config") or {}),
                "supported_accelerators": supported_accelerators,
                "supports_auto_fallback": supports_auto_fallback,
            }
        for plugin_id in sorted(plugin_ids):
            by_id.setdefault(
                plugin_id,
                {
                    "plugin_id": plugin_id,
                    "display_name": plugin_id,
                    "version": "",
                    "supported_job_types": [],
                    "supported_strategies": [],
                    "request_config_schema": {},
                    "default_request_config": {},
                    "supported_accelerators": ["cpu", "cuda", "mps"],
                    "supports_auto_fallback": True,
                },
            )
        return [by_id[key] for key in sorted(by_id.keys())]

    @staticmethod
    def _normalize_accelerator_name(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"cpu", "cuda", "mps", "auto"}:
            return raw
        if not raw:
            return ""
        if raw.startswith("cuda:"):
            return "cuda"
        parts = [item.strip() for item in raw.split(",") if item.strip()]
        if parts and all(part.isdigit() for part in parts):
            return "cuda"
        if raw.isdigit():
            return "cuda"
        return ""

    def _extract_requested_accelerator(self, job: Job) -> tuple[str | None, bool]:
        params = job.params if isinstance(job.params, dict) else {}
        resources = job.resources if isinstance(job.resources, dict) else {}

        raw_value: Any = params.get("device")
        if raw_value is None:
            raw_value = resources.get("accelerator")
        if raw_value is None:
            return None, True

        normalized = self._normalize_accelerator_name(raw_value)
        if not normalized or normalized == "auto":
            return None, True
        return normalized, False

    def _available_accelerators(self, resources: dict[str, Any]) -> set[str]:
        raw_items = (resources or {}).get("accelerators")
        available: set[str] = set()
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                accelerator = self._normalize_accelerator_name(item.get("type"))
                if accelerator and accelerator != "auto" and bool(item.get("available")):
                    available.add(accelerator)
        if not available:
            if self._to_int((resources or {}).get("gpu_count"), 0) > 0:
                available.add("cuda")
            available.add("cpu")
        return available

    def _plugin_supported_accelerators(self, runtime_session: RuntimeSession, plugin_id: str) -> set[str]:
        capability = runtime_session.plugin_capabilities.get(plugin_id) if plugin_id else None
        raw = capability.get("supported_accelerators") if isinstance(capability, dict) else None
        supported: set[str] = set()
        if isinstance(raw, list):
            for item in raw:
                accelerator = self._normalize_accelerator_name(item)
                if accelerator and accelerator != "auto":
                    supported.add(accelerator)
        if not supported:
            return {"cuda", "mps", "cpu"}
        return supported

    def _resolve_accelerator_for_session(self, job: Job, runtime_session: RuntimeSession) -> str | None:
        available = self._available_accelerators(runtime_session.resources or {})
        supported = self._plugin_supported_accelerators(runtime_session, str(job.plugin_id or ""))
        candidates = available & supported
        if not candidates:
            return None

        requested, is_auto = self._extract_requested_accelerator(job)
        if not is_auto and requested:
            return requested if requested in candidates else None

        for accelerator in ("cuda", "mps", "cpu"):
            if accelerator in candidates:
                return accelerator
        return None

    def _resource_satisfied(self, required: dict[str, Any], available: dict[str, Any]) -> bool:
        req_gpu = self._to_int((required or {}).get("gpu_count"), 0)
        req_mem = self._to_int((required or {}).get("memory_mb"), 0)
        avail_gpu = self._to_int((available or {}).get("gpu_count"), 0)
        avail_mem = self._to_int((available or {}).get("memory_mb"), 0)

        if req_gpu > 0 and avail_gpu < req_gpu:
            return False
        if req_mem > 0 and avail_mem > 0 and avail_mem < req_mem:
            return False

        req_capabilities = (required or {}).get("capabilities")
        if isinstance(req_capabilities, list):
            avail_capabilities = (available or {}).get("capabilities")
            avail_set = {str(item) for item in (avail_capabilities or [])}
            if any(str(item) not in avail_set for item in req_capabilities):
                return False

        req_labels = (required or {}).get("labels")
        if isinstance(req_labels, dict):
            avail_labels = (available or {}).get("labels")
            if not isinstance(avail_labels, dict):
                return False
            for key, value in req_labels.items():
                if str(avail_labels.get(str(key))) != str(value):
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

    @staticmethod
    def _required_recovery_tables() -> tuple[str, ...]:
        return (
            RuntimeExecutor.__tablename__,
            Job.__tablename__,
        )

    async def _has_required_recovery_tables(self, session) -> bool:
        required_tables = self._required_recovery_tables()
        connection = await session.connection()

        def _check(sync_conn) -> bool:
            table_inspector = inspect(sync_conn)
            return all(table_inspector.has_table(table_name) for table_name in required_tables)

        return await connection.run_sync(_check)

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
            if not await self._has_required_recovery_tables(session):
                logger.warning(
                    "跳过 runtime 重启恢复：缺少表结构 tables={}，等待 create_all",
                    ", ".join(self._required_recovery_tables()),
                )
                return {
                    "reset_executors": 0,
                    "recovered_pending_assignments": 0,
                    "failed_running_jobs": 0,
                    "created_retry_jobs": 0,
                }

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
            "runtime 重启恢复完成 summary={}",
            summary,
        )
        await self._try_persist_runtime_stats(force=True)
        return summary

    async def register(
            self,
            executor_id: str,
            queue: asyncio.Queue[pb.RuntimeMessage],
            version: str,
            plugin_ids: set[str],
            resources: dict[str, Any],
            plugin_capabilities: list[dict[str, Any]] | None = None,
    ) -> None:
        if not self._is_executor_allowed(executor_id):
            raise PermissionError(f"Executor {executor_id} is not in allowlist")

        normalized_capabilities = self._normalize_plugin_capabilities(plugin_ids, plugin_capabilities)
        plugin_id_set = {item["plugin_id"] for item in normalized_capabilities}

        async with self._lock:
            self._sessions[executor_id] = RuntimeSession(
                executor_id=executor_id,
                queue=queue,
                version=version,
                plugins=plugin_id_set,
                plugin_capabilities={item["plugin_id"]: item for item in normalized_capabilities},
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
            executor.plugin_ids = {"plugins": normalized_capabilities}
            executor.resources = resources
            executor.status = "idle"
            executor.is_online = True
            executor.current_job_id = None
            executor.last_seen_at = datetime.now(UTC)
            session.add(executor)
            await session.commit()

        await self._try_persist_runtime_stats(force=True)
        logger.info(
            "执行器已连接 executor_id={} version={} plugins={} resources={}",
            executor_id,
            version,
            sorted(plugin_id_set),
            resources,
        )
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

        logger.info(
            "执行器已断开 executor_id={} affected_jobs_count={}",
            executor_id,
            len(cleanup_job_ids),
        )
        await self._try_persist_runtime_stats(force=True)
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

        await self._try_persist_runtime_stats()
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

        logger.warning("检测到心跳超时执行器 stale_executor_ids={}", stale_ids)

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

        await self._try_persist_runtime_stats(force=True)

    async def assign_job(self, job: Job, check_stale: bool = True) -> Optional[AssignmentResult]:
        if check_stale:
            await self.mark_stale_executors()

        resolved_backend: str | None = None
        dispatch_params: dict[str, Any] = dict(job.params or {})

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
            candidates: list[tuple[RuntimeSession, str]] = []
            for runtime_session in self._sessions.values():
                if runtime_session.busy:
                    continue
                if job.plugin_id and job.plugin_id not in runtime_session.plugins:
                    continue
                if not self._resource_satisfied(job.resources or {}, runtime_session.resources or {}):
                    continue
                resolved = self._resolve_accelerator_for_session(job, runtime_session)
                if not resolved:
                    continue
                candidates.append((runtime_session, resolved))
            if not candidates:
                return None

            backend_priority = {"cuda": 0, "mps": 1, "cpu": 2}
            target, resolved_backend = sorted(
                candidates,
                key=lambda item: (backend_priority.get(item[1], 99), item[0].last_seen),
            )[0]
            dispatch_params["_resolved_device_backend"] = resolved_backend
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
                            params=runtime_codec.dict_to_struct(dispatch_params),
                            resources=runtime_codec.dict_to_resource_summary(job.resources or {}),
                            iteration=int(job.iteration or 0),
                        ),
                    )
                )
            )
            target.last_seen = datetime.now(UTC)
            logger.info(
                "任务已派发，等待 ACK request_id={} job_id={} executor_id={}",
                request_id,
                job_id,
                target.executor_id,
            )
            logger.info(
                "任务设备后端已解析 job_id={} executor_id={} backend={}",
                job_id,
                target.executor_id,
                resolved_backend,
            )

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
                params_payload = dict(persisted_job.params or {})
                if resolved_backend:
                    params_payload["_resolved_device_backend"] = resolved_backend
                persisted_job.params = params_payload
                session.add(persisted_job)
            await session.commit()

        await self._try_persist_runtime_stats()
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
                logger.info("已发送停止任务指令 request_id={} job_id={} reason={}", request_id, job_id, reason)
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
                        logger.info(
                            "任务已开始执行（ACK 成功） request_id={} job_id={} executor_id={}",
                            ack_for,
                            job_id,
                            pending.executor_id,
                        )
                    else:
                        job.status = TrainingJobStatus.FAILED
                        job.last_error = message or "executor reject assignment"
                        job.ended_at = datetime.now(UTC)
                        job.assigned_executor_id = None
                        logger.warning(
                            "任务派发被拒绝（ACK 失败） request_id={} job_id={} executor_id={} reason={}",
                            ack_for,
                            job_id,
                            pending.executor_id,
                            message or "executor reject assignment",
                        )
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
            stop_job_id = self._pending_stop.pop(ack_for, None)
            if is_ok:
                logger.info("停止任务请求已确认（ACK 成功） request_id={} job_id={}", ack_for, stop_job_id)
            else:
                logger.warning(
                    "停止任务请求确认失败（ACK 非 OK） request_id={} job_id={} reason={}",
                    ack_for,
                    stop_job_id,
                    message or "",
                )

        await self._try_persist_runtime_stats()

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
                logger.warning(
                    "任务派发等待 ACK 超时 request_id={} job_id={} executor_id={} timeout_sec={}",
                    pending.request_id,
                    pending.job_id,
                    pending.executor_id,
                    timeout_sec,
                )
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

        await self._try_persist_runtime_stats(force=True)
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

        await self._try_persist_runtime_stats()
        logger.info("执行器切换为空闲状态 executor_id={} job_id={}", executor_id, job_id)
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
