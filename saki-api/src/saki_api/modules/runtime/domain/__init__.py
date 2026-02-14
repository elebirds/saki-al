"""Runtime domain exports (entities + state-machine rules)."""

from saki_api.modules.runtime.domain.loop import ALLoop, Loop
from saki_api.modules.runtime.domain.loop_mode import (
    DEFAULT_MODE_POLICIES,
    LOOP_TASK_SPECS_BY_MODE,
    LoopTerminalDecision,
    phase_for_mode,
    task_specs_for_mode,
)
from saki_api.modules.runtime.domain.metric import JobSampleMetric
from saki_api.modules.runtime.domain.model import Model
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.runtime_command_log import RuntimeCommandLog
from saki_api.modules.runtime.domain.runtime_executor import RuntimeExecutor
from saki_api.modules.runtime.domain.runtime_executor_stats import RuntimeExecutorStats
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.runtime.domain.step_event import StepEvent
from saki_api.modules.runtime.domain.step_metric_point import StepMetricPoint
from saki_api.modules.runtime.domain.state_machine import (
    RUNNING_ROUND_STATES,
    RUNNING_STEP_STATES,
    TERMINAL_ROUND_STATES,
    TERMINAL_STEP_STATES,
    RoundAggregateSnapshot,
    summarize_step_states,
)

# Backward aliases.
Job = Round
JobTask = Step
TaskCandidateItem = StepCandidateItem
TaskEvent = StepEvent
TaskMetricPoint = StepMetricPoint
RUNNING_JOB_STATUSES = RUNNING_ROUND_STATES
RUNNING_TASK_STATUSES = RUNNING_STEP_STATES
TERMINAL_JOB_STATUSES = TERMINAL_ROUND_STATES
TERMINAL_TASK_STATUSES = TERMINAL_STEP_STATES
JobAggregateSnapshot = RoundAggregateSnapshot
summarize_task_statuses = summarize_step_states

__all__ = [
    "Loop",
    "ALLoop",
    "Round",
    "Step",
    "Job",
    "JobTask",
    "JobSampleMetric",
    "Model",
    "RuntimeCommandLog",
    "RuntimeExecutor",
    "RuntimeExecutorStats",
    "StepCandidateItem",
    "StepEvent",
    "StepMetricPoint",
    "TaskCandidateItem",
    "TaskEvent",
    "TaskMetricPoint",
    "DEFAULT_MODE_POLICIES",
    "LOOP_TASK_SPECS_BY_MODE",
    "LoopTerminalDecision",
    "phase_for_mode",
    "task_specs_for_mode",
    "RUNNING_ROUND_STATES",
    "RUNNING_STEP_STATES",
    "TERMINAL_ROUND_STATES",
    "TERMINAL_STEP_STATES",
    "RoundAggregateSnapshot",
    "summarize_step_states",
    "RUNNING_JOB_STATUSES",
    "RUNNING_TASK_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "JobAggregateSnapshot",
    "summarize_task_statuses",
]
