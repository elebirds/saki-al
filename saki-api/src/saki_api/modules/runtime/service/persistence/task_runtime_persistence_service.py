"""Runtime task event/result persistence service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.runtime.domain.task_event import TaskEvent
from saki_api.modules.runtime.domain.task_metric_point import TaskMetricPoint
from saki_api.modules.runtime.repo.job import JobRepository
from saki_api.modules.runtime.repo.job_task import JobTaskRepository
from saki_api.modules.runtime.repo.task_candidate_item import TaskCandidateItemRepository
from saki_api.modules.runtime.repo.task_event import TaskEventRepository
from saki_api.modules.runtime.repo.task_metric_point import TaskMetricPointRepository
from saki_api.modules.runtime.service.application.event_dto import RuntimeTaskEventDTO, RuntimeTaskResultDTO
from saki_api.modules.runtime.service.application.job_aggregation import apply_job_update, build_job_update_from_tasks
from saki_api.modules.shared.modeling.enums import JobTaskStatus


class RuntimeTaskPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.job_repo = JobRepository(session)
        self.task_repo = JobTaskRepository(session)
        self.event_repo = TaskEventRepository(session)
        self.metric_repo = TaskMetricPointRepository(session)
        self.candidate_repo = TaskCandidateItemRepository(session)

    @transactional
    async def persist_task_event(self, event: RuntimeTaskEventDTO) -> None:
        task = await self.task_repo.get_by_id(event.task_id)
        if not task:
            raise ValueError(f"task not found: {event.task_id}")

        if await self.event_repo.exists_by_task_seq(task_id=event.task_id, seq=int(event.seq)):
            return

        await self.event_repo.create(
            TaskEvent(
                task_id=event.task_id,
                seq=int(event.seq),
                ts=event.ts,
                event_type=event.event_type,
                payload=event.payload,
                request_id=event.request_id,
            ).model_dump(exclude_none=True)
        )

        if event.event_type == "status" and event.status is not None:
            task.status = event.status
            if event.status == JobTaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.now(UTC)
            if event.status in {
                JobTaskStatus.SUCCEEDED,
                JobTaskStatus.FAILED,
                JobTaskStatus.CANCELLED,
                JobTaskStatus.SKIPPED,
            }:
                task.ended_at = datetime.now(UTC)
                task.last_error = str(event.payload.get("reason") or "") or None
            self.session.add(task)

        if event.event_type == "metric":
            metric_points: list[TaskMetricPoint] = []
            metrics = event.payload.get("metrics") or {}
            for metric_name, metric_value in metrics.items():
                metric_points.append(
                    TaskMetricPoint(
                        task_id=task.id,
                        step=int(event.payload.get("step") or 0),
                        epoch=(
                            int(event.payload.get("epoch") or 0)
                            if event.payload.get("epoch") is not None
                            else None
                        ),
                        metric_name=str(metric_name),
                        metric_value=float(metric_value),
                        ts=event.ts,
                    )
                )
            await self.metric_repo.add_many(metric_points)

        if event.event_type == "artifact":
            artifacts = dict(task.artifacts or {})
            name = str(event.payload.get("name") or "")
            if name:
                artifacts[name] = {
                    "kind": str(event.payload.get("kind") or "artifact"),
                    "uri": str(event.payload.get("uri") or ""),
                    "meta": event.payload.get("meta") or {},
                }
                task.artifacts = artifacts
                self.session.add(task)

        await self._recompute_job_summary(task.job_id)

    @transactional
    async def persist_task_result(self, result: RuntimeTaskResultDTO) -> None:
        task = await self.task_repo.get_by_id(result.task_id)
        if not task:
            raise ValueError(f"task not found: {result.task_id}")

        task.status = result.status
        task.metrics = dict(result.metrics)
        task.artifacts = {
            item.name: {
                "kind": item.kind,
                "uri": item.uri,
                "meta": item.meta,
            }
            for item in result.artifacts
        }
        task.last_error = result.last_error
        task.ended_at = datetime.now(UTC)
        if not task.started_at:
            task.started_at = datetime.now(UTC)
        self.session.add(task)

        await self.candidate_repo.delete_by_task(task.id)
        for candidate in result.candidates:
            await self.candidate_repo.create(
                TaskCandidateItem(
                    task_id=task.id,
                    sample_id=uuid.UUID(str(candidate.sample_id)),
                    rank=int(candidate.rank),
                    score=float(candidate.score),
                    reason=candidate.reason,
                    prediction_snapshot={},
                ).model_dump(exclude_none=True)
            )

        metric_rows = [
            TaskMetricPoint(
                task_id=task.id,
                step=0,
                epoch=None,
                metric_name=str(metric_name),
                metric_value=float(metric_value),
                ts=datetime.now(UTC),
            )
            for metric_name, metric_value in result.metrics.items()
        ]
        await self.metric_repo.add_many(metric_rows)

        await self._recompute_job_summary(task.job_id)

    async def _recompute_job_summary(self, job_id: uuid.UUID) -> None:
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            return
        tasks = await self.task_repo.list_by_job(job_id)
        update = build_job_update_from_tasks(job=job, tasks=tasks)
        apply_job_update(job, update)
        self.session.add(job)

