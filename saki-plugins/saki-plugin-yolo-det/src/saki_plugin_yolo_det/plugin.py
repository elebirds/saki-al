"""YOLO Detection Plugin for Saki."""

from __future__ import annotations

from typing import Any

from saki_plugin_sdk import (
    EventCallback,
    ExecutorPlugin,
    StepRuntimeContext,
    TrainOutput,
    WorkspaceProtocol,
)
from saki_plugin_yolo_det.common import infer_image_hw as _runtime_infer_image_hw
from saki_plugin_yolo_det.runtime_service import YoloRuntimeService

# Keep this symbol on module-level for backward-compatible tests/monkeypatch.
_infer_image_hw = _runtime_infer_image_hw


class YoloDetectionPlugin(ExecutorPlugin):
    """YOLO Detection Plugin."""

    def __init__(self) -> None:
        super().__init__()
        self._manifest = self._load_manifest()
        self._runtime = YoloRuntimeService(supported_accelerators=self.supported_accelerators)

    async def on_load(self, context: dict[str, Any]) -> None:
        del context
        self.logger.info(
            f"YOLO Detection Plugin v{self.version} loaded. "
            f"Supported strategies: {self.supported_strategies}"
        )

    async def on_start(self, step_id: str, workspace: WorkspaceProtocol) -> None:
        await super().on_start(step_id, workspace)
        workspace.ensure()
        self.logger.debug(f"Step {step_id} workspace prepared at {workspace.root}")

    async def on_stop(self, step_id: str, workspace: WorkspaceProtocol) -> None:
        del workspace
        self.logger.debug(f"Step {step_id} completed")

    async def on_unload(self) -> None:
        self.logger.info("YOLO Detection Plugin unloading")

    def validate_params(
        self,
        params: dict[str, Any],
        *,
        context: StepRuntimeContext | None = None,
    ) -> None:
        del context
        self._runtime.validate_params(params)

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
        self.logger.info(f"Preparing dataset with {len(samples)} samples")
        await self._runtime.prepare_data(
            workspace=workspace,
            labels=labels,
            samples=samples,
            annotations=annotations,
            dataset_ir=dataset_ir,
            splits=splits,
            context=context,
        )
        self.logger.info("Dataset preparation completed")

    async def train(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: StepRuntimeContext,
    ) -> TrainOutput:
        self.logger.info(f"Starting training with params: {list(params.keys())}")
        return await self._runtime.train(
            workspace=workspace,
            params=params,
            emit=emit,
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
        self.logger.info(f"Starting eval with params: {list(params.keys())}")
        return await self._runtime.eval(
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def predict_unlabeled(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: StepRuntimeContext,
    ) -> list[dict[str, Any]]:
        self.logger.info(
            f"Running {strategy} prediction on {len(unlabeled_samples)} samples"
        )
        return await self._runtime.predict_unlabeled(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def predict_unlabeled_batch(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: StepRuntimeContext,
    ) -> list[dict[str, Any]]:
        return await self._runtime.predict_unlabeled_batch(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def stop(self, step_id: str) -> None:
        self.logger.info(f"Stop requested for step {step_id}")
        await self._runtime.stop(step_id)


__all__ = ["YoloDetectionPlugin", "_infer_image_hw"]
