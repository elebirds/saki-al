from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Callable

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import ForbiddenAppException, NotFoundAppException
from saki_api.infra.db.session import SessionLocal, bind_current_session, reset_current_session
from saki_api.modules.importing.domain import ImportTask, ImportTaskEvent, ImportTaskStatus
from saki_api.modules.importing.repo import ImportTaskRepository


EventProducerFactory = Callable[[AsyncSession], AsyncIterator[dict[str, Any]]]


class TaskService:
    _running_jobs: dict[str, asyncio.Task[None]] = {}
    _semaphore: asyncio.Semaphore | None = None

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ImportTaskRepository(session)

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(max(1, int(settings.IMPORT_MAX_CONCURRENT_TASKS)))
        return cls._semaphore

    async def create_task(
        self,
        *,
        mode: str,
        resource_type: str,
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> ImportTask:
        return await self.repo.create_task(
            {
                "mode": mode,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "user_id": user_id,
                "status": ImportTaskStatus.QUEUED.value,
                "payload": payload,
            }
        )

    async def get_task_for_user(self, *, task_id: uuid.UUID, user_id: uuid.UUID) -> ImportTask:
        task = await self.repo.get_task(task_id)
        if not task:
            raise NotFoundAppException(f"Import task {task_id} not found")
        if task.user_id != user_id:
            raise ForbiddenAppException("Import task does not belong to current user")
        return task

    async def get_status_payload(self, *, task_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        task = await self.get_task_for_user(task_id=task_id, user_id=user_id)
        return {
            "task_id": task.id,
            "status": str(task.status),
            "progress": {
                "current": int(task.progress_current or 0),
                "total": int(task.progress_total or 0),
            },
            "summary": dict(task.summary or {}),
            "error": task.error,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }

    async def list_events_for_user(
        self,
        *,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        after_seq: int,
        limit: int = 500,
    ) -> tuple[ImportTask, list[dict[str, Any]]]:
        task = await self.get_task_for_user(task_id=task_id, user_id=user_id)
        rows = await self.repo.list_events_after(task_id=task_id, after_seq=max(0, int(after_seq)), limit=limit)
        normalized_rows: list[ImportTaskEvent] = []
        for row in rows:
            if isinstance(row, ImportTaskEvent):
                normalized_rows.append(row)
                continue
            mapping = getattr(row, "_mapping", None)
            if mapping:
                candidate = mapping.get("ImportTaskEvent")
                if isinstance(candidate, ImportTaskEvent):
                    normalized_rows.append(candidate)
        payload = [
            {
                "seq": int(row.seq),
                "ts": row.ts.isoformat(),
                "event": row.event_type,
                "event_subtype": row.event_subtype,
                "phase": row.phase,
                "message": row.message,
                "current": row.current,
                "total": row.total,
                "item_key": row.item_key,
                "status": row.status,
                "detail": dict(row.detail or {}),
            }
            for row in normalized_rows
        ]
        return task, payload

    @classmethod
    def schedule_streaming_job(
        cls,
        *,
        task_id: uuid.UUID,
        producer_factory: EventProducerFactory,
    ) -> None:
        task_key = str(task_id)
        loop = asyncio.get_running_loop()
        job = loop.create_task(cls._run_streaming_job(task_id=task_id, producer_factory=producer_factory))
        cls._running_jobs[task_key] = job

        def _cleanup(done: asyncio.Task[None]) -> None:
            del done
            cls._running_jobs.pop(task_key, None)

        job.add_done_callback(_cleanup)

    @classmethod
    async def _run_streaming_job(
        cls,
        *,
        task_id: uuid.UUID,
        producer_factory: EventProducerFactory,
    ) -> None:
        semaphore = cls._get_semaphore()
        async with semaphore:
            async with SessionLocal() as session:
                token = bind_current_session(session)
                service = TaskService(session)
                try:
                    task = await service.repo.get_task(task_id)
                    if not task:
                        logger.error("import task missing before start task_id={}", task_id)
                        return

                    task.status = ImportTaskStatus.RUNNING.value
                    if task.started_at is None:
                        task.started_at = datetime.now(UTC)
                    await session.commit()

                    seq = await service.repo.get_last_seq(task_id=task_id)
                    got_complete = False
                    producer = producer_factory(session)
                    async for event in producer:
                        seq += 1
                        await service._append_event(task=task, seq=seq, event=event)
                        if str(event.get("event") or "") == "complete":
                            got_complete = True
                        await session.commit()

                    if not got_complete:
                        seq = await service._append_terminal_failure(
                            task=task,
                            seq=seq,
                            error="import task finished unexpectedly without complete event",
                            code="MISSING_COMPLETE_EVENT",
                        )
                        del seq
                        await session.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("import task job failed task_id={} error={}", task_id, exc)
                    await session.rollback()
                    task = await service.repo.get_task(task_id)
                    if task:
                        seq = await service.repo.get_last_seq(task_id=task_id)
                        seq = await service._append_terminal_failure(
                            task=task,
                            seq=seq,
                            error=str(exc),
                            code="TASK_EXECUTION_FAILED",
                        )
                        del seq
                        await session.commit()
                finally:
                    reset_current_session(token)

    async def _append_event(self, *, task: ImportTask, seq: int, event: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        event_type = str(event.get("event") or "item")
        detail = event.get("detail")
        if not isinstance(detail, dict):
            detail = {}

        await self.repo.append_events(
            [
                {
                    "task_id": task.id,
                    "seq": seq,
                    "ts": now,
                    "event_type": event_type,
                    "event_subtype": str(event.get("event_subtype") or "") or None,
                    "phase": str(event.get("phase") or "") or None,
                    "message": str(event.get("message") or "") or None,
                    "current": int(event["current"]) if isinstance(event.get("current"), int) else None,
                    "total": int(event["total"]) if isinstance(event.get("total"), int) else None,
                    "item_key": str(event.get("item_key") or "") or None,
                    "status": str(event.get("status") or "") or None,
                    "detail": detail,
                }
            ]
        )

        if isinstance(event.get("phase"), str) and str(event.get("phase") or ""):
            task.phase = str(event.get("phase"))
        if isinstance(event.get("current"), int):
            task.progress_current = max(0, int(event.get("current") or 0))
        if isinstance(event.get("total"), int):
            task.progress_total = max(0, int(event.get("total") or 0))

        if event_type == "complete":
            task.finished_at = now
            task.summary = detail
            if bool(detail.get("failed")):
                task.status = ImportTaskStatus.FAILED.value
                task.error = str(detail.get("error") or task.error or "import task failed")
            elif bool(detail.get("canceled")):
                task.status = ImportTaskStatus.CANCELED.value
            else:
                task.status = ImportTaskStatus.SUCCESS.value

    async def _append_terminal_failure(
        self,
        *,
        task: ImportTask,
        seq: int,
        error: str,
        code: str,
    ) -> int:
        await self._append_event(
            task=task,
            seq=seq + 1,
            event={
                "event": "error",
                "message": error,
                "detail": {"code": code},
            },
        )
        await self._append_event(
            task=task,
            seq=seq + 2,
            event={
                "event": "complete",
                "message": "import task terminated",
                "detail": {"failed": True, "error": error, "code": code},
            },
        )
        task.status = ImportTaskStatus.FAILED.value
        task.error = error
        task.finished_at = datetime.now(UTC)
        return seq + 2
