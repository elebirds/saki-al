"""Runtime job aggregation use-cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from saki_api.modules.runtime.api.job import JobUpdate
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.state_machine import TERMINAL_ROUND_STATES, summarize_step_states
from saki_api.modules.shared.modeling.enums import RoundStatus


def build_job_update_from_tasks(*, job: Round, tasks: Iterable[Step]) -> JobUpdate:
    task_rows = list(tasks)
    if not task_rows:
        return JobUpdate(
            state=RoundStatus.PENDING,
            step_counts={},
            final_metrics={},
            final_artifacts={},
        )

    snapshot = summarize_step_states(task.state for task in task_rows)
    payload = JobUpdate(
        state=snapshot.state,
        step_counts=snapshot.step_counts,
    )

    if snapshot.state == RoundStatus.RUNNING and not job.started_at:
        payload.started_at = datetime.now(UTC)
    if snapshot.state in TERMINAL_ROUND_STATES and not job.ended_at:
        payload.ended_at = datetime.now(UTC)

    last_task = task_rows[-1]
    payload.final_metrics = dict(last_task.metrics or {})
    payload.final_artifacts = dict(last_task.artifacts or {})
    if last_task.output_commit_id:
        payload.output_commit_id = last_task.output_commit_id
    if last_task.last_error:
        payload.terminal_reason = last_task.last_error
    return payload


def apply_job_update(job: Round, update: JobUpdate) -> None:
    payload = update.model_dump(exclude_none=True)
    for key, value in payload.items():
        setattr(job, key, value)
