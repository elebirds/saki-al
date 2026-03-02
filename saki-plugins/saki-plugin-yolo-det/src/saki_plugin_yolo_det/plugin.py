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
            f"YOLO 检测插件 v{self.version} 已加载。"
            f"支持的策略：{self.supported_strategies}"
        )

    async def on_start(self, step_id: str, workspace: WorkspaceProtocol) -> None:
        await super().on_start(step_id, workspace)
        workspace.ensure()
        self.logger.debug(f"step {step_id} 的工作目录已准备完成：{workspace.root}")

    async def on_stop(self, step_id: str, workspace: WorkspaceProtocol) -> None:
        del workspace
        self.logger.debug(f"step {step_id} 已完成")

    async def on_unload(self) -> None:
        self.logger.info("YOLO 检测插件正在卸载")

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
        self.logger.info(f"正在准备数据集，样本数：{len(samples)}")
        await self._runtime.prepare_data(
            workspace=workspace,
            labels=labels,
            samples=samples,
            annotations=annotations,
            dataset_ir=dataset_ir,
            splits=splits,
            context=context,
        )
        self.logger.info("数据集准备完成")

    async def train(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: StepRuntimeContext,
    ) -> TrainOutput:
        self.logger.info(f"开始训练，参数键：{list(params.keys())}")
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
        self.logger.info(f"开始评估，参数键：{list(params.keys())}")
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
            f"正在执行 {strategy} 预测，未标注样本数：{len(unlabeled_samples)}"
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
        self.logger.info(f"收到 step {step_id} 的停止请求")
        await self._runtime.stop(step_id)


__all__ = ["YoloDetectionPlugin", "_infer_image_hw"]
