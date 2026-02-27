"""YOLO Detection Plugin for Saki.

A production-ready plugin for training and inference with YOLO models,
supporting both standard detection (detect) and oriented bounding boxes (OBB).
"""

from __future__ import annotations

from typing import Any

from saki_plugin_sdk import (
    EventCallback,
    ExecutorPlugin,
    PluginLogger,
    TrainOutput,
    Workspace,
)
from saki_plugin_yolo_det.internal import (
    YoloDetectionInternal,
    _infer_image_hw as _internal_infer_image_hw,
)

# Keep this symbol on module-level for backward-compatible tests/monkeypatch.
_infer_image_hw = _internal_infer_image_hw


class YoloDetectionPlugin(ExecutorPlugin):
    """YOLO Detection Plugin.

    Supports:
    - Standard object detection (detect)
    - Oriented bounding box detection (OBB)
    - Multiple accelerator backends (CUDA, MPS, CPU)
    - Active learning strategies (uncertainty, IoU disagreement, random)

    Metadata (plugin_id, version, etc.) is automatically loaded from plugin.yml
    via the ExecutorPlugin base class.
    """

    def __init__(self) -> None:
        # Initialize base class (sets up logger and loads manifest)
        super().__init__()
        # Load manifest from plugin.yml
        self._manifest = self._load_manifest()
        # Initialize internal implementation
        self._internal = YoloDetectionInternal()

    # -------------------------------------------------------------------
    # Lifecycle hooks (optional overrides with logging)
    # -------------------------------------------------------------------

    async def on_load(self, context: dict[str, Any]) -> None:
        """Plugin initialization hook.

        Called when worker process starts. Log plugin version and capabilities.
        """
        self.logger.info(
            f"YOLO Detection Plugin v{self.version} loaded. "
            f"Supported strategies: {self.supported_strategies}"
        )

    async def on_start(self, step_id: str, workspace: Workspace) -> None:
        """Step start hook.

        Called before step execution. Ensures workspace directories exist.
        """
        await super().on_start(step_id, workspace)
        workspace.ensure()
        self.logger.debug(f"Step {step_id} workspace prepared at {workspace.root}")

    async def on_stop(self, step_id: str, workspace: Workspace) -> None:
        """Step completion hook.

        Called after step execution (success or failure).
        """
        self.logger.debug(f"Step {step_id} completed")

    async def on_unload(self) -> None:
        """Plugin cleanup hook.

        Called when worker process shuts down.
        """
        self.logger.info("YOLO Detection Plugin unloading")

    # -------------------------------------------------------------------
    # Execution methods
    # -------------------------------------------------------------------

    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.logger.info(f"Preparing dataset with {len(samples)} samples")
        await self._internal.prepare_data(
            workspace=workspace,
            labels=labels,
            samples=samples,
            annotations=annotations,
            dataset_ir=dataset_ir,
            infer_image_hw=_infer_image_hw,
            splits=splits,
        )
        self.logger.info("Dataset preparation completed")

    async def train(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        """Execute training step.

        Args:
            workspace: Step workspace directory
            params: Resolved configuration parameters
            emit: Event callback for progress/metrics

        Returns:
            Training output with metrics and artifacts
        """
        self.logger.info(f"Starting training with params: {list(params.keys())}")
        return await self._internal.train(workspace, params, emit)

    async def eval(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        self.logger.info(f"Starting eval with params: {list(params.keys())}")
        return await self._internal.eval(workspace, params, emit)

    async def export(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        self.logger.info(f"Starting export with params: {list(params.keys())}")
        return await self._internal.export(workspace, params, emit)

    async def upload_artifact(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        self.logger.info(f"Starting upload_artifact with params: {list(params.keys())}")
        return await self._internal.upload_artifact(workspace, params, emit)

    async def predict_unlabeled(
        self,
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run prediction on unlabeled samples.

        Args:
            workspace: Step workspace directory
            unlabeled_samples: Samples to predict
            strategy: Sampling strategy name
            params: Resolved configuration parameters

        Returns:
            Prediction results with scores
        """
        self.logger.info(
            f"Running {strategy} prediction on {len(unlabeled_samples)} samples"
        )
        return await self._internal.predict_unlabeled(
            workspace, unlabeled_samples, strategy, params
        )

    async def predict_unlabeled_batch(
        self,
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Batch prediction (delegates to predict_unlabeled)."""
        return await self._internal.predict_unlabeled_batch(
            workspace, unlabeled_samples, strategy, params
        )

    async def stop(self, step_id: str) -> None:
        """Request graceful training stop."""
        self.logger.info(f"Stop requested for step {step_id}")
        await self._internal.stop(step_id)


__all__ = ["YoloDetectionPlugin", "_infer_image_hw"]
