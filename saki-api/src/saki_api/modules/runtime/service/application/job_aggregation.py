"""Runtime job aggregation use-cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from saki_api.modules.runtime.api.job import JobUpdate
from saki_api.modules.runtime.domain.job import Job
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.runtime.domain.state_machine import TERMINAL_JOB_STATUSES, summarize_task_statuses
from saki_api.modules.shared.modeling.enums import JobStatusV2


def build_job_update_from_tasks(*, job: Job, tasks: Iterable[JobTask]) -> JobUpdate:
    task_rows = list(tasks)
    if not task_rows:
        return JobUpdate(
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            final_metrics={},
            final_artifacts={},
        )

    snapshot = summarize_task_statuses(task.status for task in task_rows)
    payload = JobUpdate(
        summary_status=snapshot.summary_status,
        task_counts=snapshot.task_counts,
    )

    if snapshot.summary_status == JobStatusV2.JOB_RUNNING and not job.started_at:
        payload.started_at = datetime.now(UTC)
    if snapshot.summary_status in TERMINAL_JOB_STATUSES and not job.ended_at:
        payload.ended_at = datetime.now(UTC)

    last_task = task_rows[-1]
    payload.final_metrics = dict(last_task.metrics or {})
    payload.final_artifacts = dict(last_task.artifacts or {})
    if last_task.result_commit_id:
        payload.result_commit_id = last_task.result_commit_id
    if last_task.last_error:
        payload.last_error = last_task.last_error
    return payload


def apply_job_update(job: Job, update: JobUpdate) -> None:
    payload = update.model_dump(exclude_none=True)
    for key, value in payload.items():
        setattr(job, key, value)
