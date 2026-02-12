"""Runtime status-machine domain rules."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from saki_api.modules.shared.modeling.enums import JobStatusV2, JobTaskStatus

TERMINAL_TASK_STATUSES: set[JobTaskStatus] = {
    JobTaskStatus.SUCCEEDED,
    JobTaskStatus.FAILED,
    JobTaskStatus.CANCELLED,
    JobTaskStatus.SKIPPED,
}

RUNNING_TASK_STATUSES: set[JobTaskStatus] = {
    JobTaskStatus.RUNNING,
    JobTaskStatus.DISPATCHING,
    JobTaskStatus.RETRYING,
}

TERMINAL_JOB_STATUSES: set[JobStatusV2] = {
    JobStatusV2.JOB_SUCCEEDED,
    JobStatusV2.JOB_PARTIAL_FAILED,
    JobStatusV2.JOB_FAILED,
    JobStatusV2.JOB_CANCELLED,
}

RUNNING_JOB_STATUSES: set[JobStatusV2] = {
    JobStatusV2.JOB_PENDING,
    JobStatusV2.JOB_RUNNING,
}


@dataclass(slots=True, frozen=True)
class JobAggregateSnapshot:
    summary_status: JobStatusV2
    task_counts: dict[str, int]
    all_terminal: bool
    any_running: bool
    any_failed: bool
    any_cancelled: bool
    all_succeeded: bool


def summarize_task_statuses(statuses: Iterable[JobTaskStatus]) -> JobAggregateSnapshot:
    values = list(statuses)
    if not values:
        return JobAggregateSnapshot(
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            all_terminal=False,
            any_running=False,
            any_failed=False,
            any_cancelled=False,
            all_succeeded=False,
        )

    counter = Counter(item.value for item in values)
    all_terminal = all(item in TERMINAL_TASK_STATUSES for item in values)
    any_running = any(item in RUNNING_TASK_STATUSES for item in values)
    any_failed = any(item == JobTaskStatus.FAILED for item in values)
    any_cancelled = any(item == JobTaskStatus.CANCELLED for item in values)
    all_succeeded = all(item in {JobTaskStatus.SUCCEEDED, JobTaskStatus.SKIPPED} for item in values)

    if any_running:
        summary = JobStatusV2.JOB_RUNNING
    elif all_terminal and all_succeeded:
        summary = JobStatusV2.JOB_SUCCEEDED
    elif all_terminal and any_cancelled and not any_failed:
        summary = JobStatusV2.JOB_CANCELLED
    elif all_terminal and any_failed and all(item == JobTaskStatus.FAILED for item in values):
        summary = JobStatusV2.JOB_FAILED
    elif all_terminal and (any_failed or any_cancelled):
        summary = JobStatusV2.JOB_PARTIAL_FAILED
    else:
        summary = JobStatusV2.JOB_PENDING

    return JobAggregateSnapshot(
        summary_status=summary,
        task_counts=dict(counter),
        all_terminal=all_terminal,
        any_running=any_running,
        any_failed=any_failed,
        any_cancelled=any_cancelled,
        all_succeeded=all_succeeded,
    )

