from __future__ import annotations

from typing import Any

from saki_plugin_sdk import (
    EventCallback,
    ExecutorPlugin,
    StepRuntimeContext,
    TrainOutput,
    WorkspaceProtocol,
)
from saki_plugin_demo_det.internal import DemoDetectionInternal


class DemoDetectionPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._manifest = self._load_manifest()
        self._internal = DemoDetectionInternal()

    async def prepare_data(
            self,
            workspace: WorkspaceProtocol,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: StepRuntimeContext,
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
            context: StepRuntimeContext,
    ) -> TrainOutput:
        return await self._internal.train(workspace, params, emit, context=context)

    async def predict_unlabeled(
            self,
            workspace: WorkspaceProtocol,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: StepRuntimeContext,
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
            context: StepRuntimeContext,
    ) -> TrainOutput:
        return await self._internal.eval(workspace, params, emit, context=context)

    async def stop(self, step_id: str) -> None:
        await self._internal.stop(step_id)
