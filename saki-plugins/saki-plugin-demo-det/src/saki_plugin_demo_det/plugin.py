from __future__ import annotations

from typing import Any

from saki_plugin_sdk import (
    ExecutionBindingContext,
    EventCallback,
    ExecutorPlugin,
    RuntimeCapabilitySnapshot,
    TaskRuntimeContext,
    TrainOutput,
    WorkspaceProtocol,
)
from saki_plugin_demo_det.internal import DemoDetectionInternal


class DemoDetectionPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._manifest = self._load_manifest()
        self._internal = DemoDetectionInternal()

    async def probe_runtime_capability(
        self,
        *,
        context: TaskRuntimeContext,
    ) -> RuntimeCapabilitySnapshot:
        del context
        return RuntimeCapabilitySnapshot(
            framework="demo",
            framework_version=self.version,
            backends=["cpu"],
            backend_details={},
            errors=[],
        )

    async def prepare_data(
            self,
            workspace: WorkspaceProtocol,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: ExecutionBindingContext,
    ) -> None:
        await self._internal.prepare_data(
            workspace,
            labels,
            samples,
            annotations,
            dataset_ir,
            splits=splits,
            context=context,
        )

    async def train(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: ExecutionBindingContext,
    ) -> TrainOutput:
        return await self._internal.train(workspace, params, emit, context=context)

    async def predict_unlabeled(
            self,
            workspace: WorkspaceProtocol,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        return await self._internal.predict_unlabeled(
            workspace,
            unlabeled_samples,
            strategy,
            params,
            context=context,
        )

    async def eval(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: ExecutionBindingContext,
    ) -> TrainOutput:
        return await self._internal.eval(workspace, params, emit, context=context)

    async def stop(self, task_id: str) -> None:
        await self._internal.stop(task_id)
