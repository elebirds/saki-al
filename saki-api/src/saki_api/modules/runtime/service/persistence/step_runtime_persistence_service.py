"""Runtime step event/result persistence service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.runtime.domain.step_event import StepEvent
from saki_api.modules.runtime.domain.step_metric_point import StepMetricPoint
from saki_api.modules.runtime.repo.round import RoundRepository
from saki_api.modules.runtime.repo.step import StepRepository
from saki_api.modules.runtime.repo.step_candidate_item import StepCandidateItemRepository
from saki_api.modules.runtime.repo.step_event import StepEventRepository
from saki_api.modules.runtime.repo.step_metric_point import StepMetricPointRepository
from saki_api.modules.runtime.service.application.event_dto import RuntimeStepEventDTO, RuntimeStepResultDTO
from saki_api.modules.runtime.service.application.round_aggregation import apply_round_update, build_round_update_from_steps
from saki_api.modules.shared.modeling.enums import StepStatus


class RuntimeStepPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.round_repo = RoundRepository(session)
        self.step_repo = StepRepository(session)
        self.event_repo = StepEventRepository(session)
        self.metric_repo = StepMetricPointRepository(session)
        self.candidate_repo = StepCandidateItemRepository(session)

    @transactional
    async def persist_step_event(self, event: RuntimeStepEventDTO) -> None:
        step = await self.step_repo.get_by_id(event.step_id)
        if not step:
            raise ValueError(f"step not found: {event.step_id}")

        if await self.event_repo.exists_by_step_seq(step_id=event.step_id, seq=int(event.seq)):
            return

        await self.event_repo.create(
            StepEvent(
                step_id=event.step_id,
                seq=int(event.seq),
                ts=event.ts,
                event_type=event.event_type,
                payload=event.payload,
                request_id=event.request_id,
            ).model_dump(exclude_none=True)
        )

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

        if event.event_type == "metric":
            metric_points: list[StepMetricPoint] = []
            metrics = event.payload.get("metrics") or {}
            for metric_name, metric_value in metrics.items():
                metric_points.append(
                    StepMetricPoint(
                        step_id=step.id,
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
    async def persist_step_result(self, result: RuntimeStepResultDTO) -> None:
        step = await self.step_repo.get_by_id(result.step_id)
        if not step:
            raise ValueError(f"step not found: {result.step_id}")

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
        if not step.started_at:
            step.started_at = datetime.now(UTC)
        self.session.add(step)

        await self.candidate_repo.delete_by_step(step.id)
        for candidate in result.candidates:
            await self.candidate_repo.create(
                StepCandidateItem(
                    step_id=step.id,
                    sample_id=uuid.UUID(str(candidate.sample_id)),
                    rank=int(candidate.rank),
                    score=float(candidate.score),
                    reason=candidate.reason,
                    prediction_snapshot=dict(candidate.prediction_snapshot or {}),
                ).model_dump(exclude_none=True)
            )

        metric_rows = [
            StepMetricPoint(
                step_id=step.id,
                metric_step=0,
                epoch=None,
                metric_name=str(metric_name),
                metric_value=float(metric_value),
                ts=datetime.now(UTC),
            )
            for metric_name, metric_value in result.metrics.items()
        ]
        await self.metric_repo.add_many(metric_rows)

        await self._recompute_round_summary(step.round_id)

    async def _recompute_round_summary(self, round_id: uuid.UUID) -> None:
        round_row = await self.round_repo.get_by_id(round_id)
        if not round_row:
            return
        steps = await self.step_repo.list_by_round(round_id)
        update = build_round_update_from_steps(round_row=round_row, steps=steps)
        apply_round_update(round_row, update)
        self.session.add(round_row)
