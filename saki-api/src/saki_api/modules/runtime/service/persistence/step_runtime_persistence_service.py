"""Runtime task event/result persistence service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.domain.step_candidate_item import TaskCandidateItem
from saki_api.modules.runtime.domain.step_event import TaskEvent
from saki_api.modules.runtime.domain.step_metric_point import TaskMetricPoint
from saki_api.modules.runtime.repo.round import RoundRepository
from saki_api.modules.runtime.repo.step import StepRepository
from saki_api.modules.runtime.repo.step_candidate_item import TaskCandidateItemRepository
from saki_api.modules.runtime.repo.step_event import TaskEventRepository
from saki_api.modules.runtime.repo.step_metric_point import TaskMetricPointRepository
from saki_api.modules.runtime.repo.task import TaskRepository
from saki_api.modules.runtime.service.application.event_dto import (
    RuntimeStepEventDTO,
    RuntimeStepResultDTO,
    RuntimeTaskEventDTO,
    RuntimeTaskResultDTO,
)
from saki_api.modules.runtime.service.application.round_aggregation import apply_round_update, build_round_update_from_steps
from saki_api.modules.shared.modeling.enums import RuntimeTaskKind, RuntimeTaskStatus, RuntimeTaskType, StepStatus, StepType


class RuntimeTaskPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.round_repo = RoundRepository(session)
        self.step_repo = StepRepository(session)
        self.task_repo = TaskRepository(session)
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
            ).model_dump(exclude_none=True)
        )

        if event.event_type == "status" and event.status is not None:
            task_status = self._to_runtime_task_status(event.status)
            task.status = task_status
            reason = str(event.payload.get("reason") or "").strip()
            if task_status == RuntimeTaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.now(UTC)
            if task_status in {
                RuntimeTaskStatus.SUCCEEDED,
                RuntimeTaskStatus.FAILED,
                RuntimeTaskStatus.CANCELLED,
                RuntimeTaskStatus.SKIPPED,
            }:
                if task.started_at is None:
                    task.started_at = datetime.now(UTC)
                task.ended_at = task.ended_at or datetime.now(UTC)
                task.last_error = reason or None
            self.session.add(task)

        if event.event_type == "metric":
            metric_points: list[TaskMetricPoint] = []
            metrics = event.payload.get("metrics") or {}
            for metric_name, metric_value in metrics.items():
                metric_points.append(
                    TaskMetricPoint(
                        task_id=task.id,
                        metric_step=int(event.payload.get("step") or 0),
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

        if event.step_id is None:
            return
        step = await self.step_repo.get_by_id(event.step_id)
        if not step:
            return

        if event.event_type == "status" and event.status is not None:
            step.state = event.status
            if event.status == StepStatus.RUNNING and not step.started_at:
                step.started_at = datetime.now(UTC)
            if event.status in {
                StepStatus.SUCCEEDED,
                StepStatus.FAILED,
                StepStatus.CANCELLED,
                StepStatus.SKIPPED,
            }:
                step.ended_at = datetime.now(UTC)
                step.last_error = str(event.payload.get("reason") or "") or None
            self.session.add(step)

        if event.event_type == "artifact":
            artifacts = dict(step.artifacts or {})
            name = str(event.payload.get("name") or "")
            if name:
                artifacts[name] = {
                    "kind": str(event.payload.get("kind") or "artifact"),
                    "uri": str(event.payload.get("uri") or ""),
                    "meta": event.payload.get("meta") or {},
                }
                step.artifacts = artifacts
                self.session.add(step)

        await self._recompute_round_summary(step.round_id)

    @transactional
    async def persist_step_event(self, event: RuntimeStepEventDTO) -> None:
        step = await self.step_repo.get_by_id(event.step_id)
        if step is None:
            raise ValueError(f"step task binding not found: {event.step_id}")
        if step.task_id is None:
            step.task_id = await self._ensure_task_binding_for_step(step.id)
            self.session.add(step)
        await self.persist_task_event(
            RuntimeTaskEventDTO(
                task_id=step.task_id,
                step_id=step.id,
                seq=event.seq,
                ts=event.ts,
                event_type=event.event_type,
                payload=dict(event.payload or {}),
                status=event.status,
                request_id=event.request_id,
            )
        )

    @transactional
    async def persist_task_result(self, result: RuntimeTaskResultDTO) -> None:
        task = await self.task_repo.get_by_id(result.task_id)
        if not task:
            raise ValueError(f"task not found: {result.task_id}")

        task.status = self._to_runtime_task_status(result.status)
        task.last_error = result.last_error
        task.started_at = task.started_at or datetime.now(UTC)
        task.ended_at = datetime.now(UTC)

        resolved_params = dict(task.resolved_params or {})
        resolved_params["_result_metrics"] = dict(result.metrics)
        resolved_params["_result_artifacts"] = {
            item.name: {
                "kind": item.kind,
                "uri": item.uri,
                "meta": item.meta,
            }
            for item in result.artifacts
            if str(item.name or "").strip()
        }
        task.resolved_params = resolved_params
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
                    prediction_snapshot=dict(candidate.prediction_snapshot or {}),
                ).model_dump(exclude_none=True)
            )

        if result.step_id is None:
            return
        step = await self.step_repo.get_by_id(result.step_id)
        if not step:
            return

        step.state = result.status
        step.metrics = dict(result.metrics)
        step.artifacts = {
            item.name: {
                "kind": item.kind,
                "uri": item.uri,
                "meta": item.meta,
            }
            for item in result.artifacts
        }
        step.last_error = result.last_error
        step.ended_at = datetime.now(UTC)
        step.started_at = step.started_at or datetime.now(UTC)
        self.session.add(step)
        await self._recompute_round_summary(step.round_id)

    @transactional
    async def persist_step_result(self, result: RuntimeStepResultDTO) -> None:
        step = await self.step_repo.get_by_id(result.step_id)
        if step is None:
            raise ValueError(f"step task binding not found: {result.step_id}")
        if step.task_id is None:
            step.task_id = await self._ensure_task_binding_for_step(step.id)
            self.session.add(step)
        await self.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=step.task_id,
                step_id=step.id,
                status=result.status,
                metrics=dict(result.metrics or {}),
                artifacts=list(result.artifacts or []),
                candidates=list(result.candidates or []),
                last_error=result.last_error,
            )
        )

    async def _recompute_round_summary(self, round_id: uuid.UUID) -> None:
        round_row = await self.round_repo.get_by_id(round_id)
        if not round_row:
            return
        steps = await self.step_repo.list_by_round(round_id)
        update = build_round_update_from_steps(round_row=round_row, steps=steps)
        apply_round_update(round_row, update)
        self.session.add(round_row)

    @staticmethod
    def _to_runtime_task_status(step_status: StepStatus) -> RuntimeTaskStatus:
        text = str(getattr(step_status, "value", step_status) or "").strip().lower()
        for item in RuntimeTaskStatus:
            if item.value == text:
                return item
        return RuntimeTaskStatus.FAILED

    @staticmethod
    def _to_runtime_task_type(step_type: StepType) -> RuntimeTaskType:
        text = str(getattr(step_type, "value", step_type) or "").strip().lower()
        for item in RuntimeTaskType:
            if item.value == text:
                return item
        return RuntimeTaskType.CUSTOM

    async def _ensure_task_binding_for_step(self, step_id: uuid.UUID) -> uuid.UUID:
        step = await self.step_repo.get_by_id_or_raise(step_id)
        if step.task_id is not None:
            return step.task_id
        round_row = await self.round_repo.get_by_id_or_raise(step.round_id)
        task = await self.task_repo.create(
            {
                "project_id": round_row.project_id,
                "kind": RuntimeTaskKind.STEP,
                "task_type": self._to_runtime_task_type(step.step_type),
                "status": self._to_runtime_task_status(step.state),
                "plugin_id": str(round_row.plugin_id or ""),
                "input_commit_id": step.input_commit_id,
                "resolved_params": dict(step.resolved_params or {}),
                "assigned_executor_id": step.assigned_executor_id,
                "attempt": int(step.attempt or 1),
                "max_attempts": int(step.max_attempts or 1),
                "started_at": step.started_at,
                "ended_at": step.ended_at,
                "last_error": step.last_error,
            }
        )
        return task.id


# Legacy alias, kept for incremental refactor of imports.
RuntimeStepPersistenceService = RuntimeTaskPersistenceService
