from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from saki_executor.steps.contracts import TaskExecutionRequest
from saki_plugin_sdk import (
    ExecutionBindingContext,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    RuntimeProfileSpec,
    TaskRuntimeContext,
)


@dataclass(frozen=True, slots=True)
class TaskExecutionPlan:
    request: TaskExecutionRequest
    metadata_plugin: Any
    host_capability: HostCapabilitySnapshot
    runtime_context: TaskRuntimeContext
    effective_plugin_params: dict[str, Any]
    selected_profile: RuntimeProfileSpec
    worker_python: str | Path | None = None
    entrypoint_module: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    def with_runtime_environment(
        self,
        *,
        worker_python: str | Path | None,
        entrypoint_module: str | None,
        extra_env: dict[str, str] | None,
    ) -> TaskExecutionPlan:
        return replace(
            self,
            worker_python=worker_python,
            entrypoint_module=entrypoint_module,
            extra_env=dict(extra_env or {}),
        )

    def with_runtime_context(self, runtime_context: TaskRuntimeContext) -> TaskExecutionPlan:
        return replace(self, runtime_context=runtime_context)


@dataclass(frozen=True, slots=True)
class BoundExecutionPlan:
    plan: TaskExecutionPlan
    runtime_capability: RuntimeCapabilitySnapshot
    execution_context: ExecutionBindingContext
    effective_plugin_params: dict[str, Any]
