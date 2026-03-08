"""Oriented R-CNN 插件入口。"""

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

from saki_plugin_oriented_rcnn.runtime_service import OrientedRCNNRuntimeService


class OrientedRCNNPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._manifest = self._load_manifest()
        self._runtime = OrientedRCNNRuntimeService()

    async def on_load(self, context: dict[str, Any]) -> None:
        del context
        self.logger.info(
            f"Oriented R-CNN 插件 v{self.version} 已加载，支持策略：{self.supported_strategies}"
        )
        self.logger.info(self._build_init_config_log())

    def _build_init_config_log(self) -> str:
        schema = self.request_config_schema() or {}
        fields = schema.get("fields") if isinstance(schema, dict) else None
        if not isinstance(fields, list):
            return "插件初始化配置摘要：未找到 config_schema.fields。"

        by_key = {
            str(item.get("key") or "").strip(): item
            for item in fields
            if isinstance(item, dict)
        }
        mode_field = by_key.get("aug_iou_iou_mode", {})
        d_field = by_key.get("aug_iou_boundary_d", {})
        augs_field = by_key.get("aug_iou_enabled_augs", {})

        mode_default = str(mode_field.get("default") or "obb")
        mode_options_raw = mode_field.get("options")
        mode_options = [
            str(item.get("value") or "").strip()
            for item in (mode_options_raw if isinstance(mode_options_raw, list) else [])
            if isinstance(item, dict) and str(item.get("value") or "").strip()
        ]
        mode_options_text = "/".join(mode_options) if mode_options else "rect/obb/boundary"

        d_default = int(d_field.get("default") or 3)
        d_props = d_field.get("props") if isinstance(d_field.get("props"), dict) else {}
        d_min = int(d_props.get("min") or 1)
        d_max = int(d_props.get("max") or 128)

        aug_default_raw = augs_field.get("default")
        aug_default_count = len(aug_default_raw) if isinstance(aug_default_raw, list) else 0

        return (
            "插件初始化配置摘要："
            f"aug_iou_iou_mode 默认={mode_default} 可选={mode_options_text}；"
            f"aug_iou_boundary_d 默认={d_default} 范围=[{d_min},{d_max}]；"
            f"aug_iou_enabled_augs 默认项数={aug_default_count}。"
        )

    async def on_start(self, task_id: str, workspace: WorkspaceProtocol) -> None:
        await super().on_start(task_id, workspace)
        workspace.ensure()
        self.logger.debug(f"step {task_id} 工作目录已准备：{workspace.root}")

    async def on_stop(self, task_id: str, workspace: WorkspaceProtocol) -> None:
        del workspace
        self.logger.debug(f"step {task_id} 已结束")

    async def on_unload(self) -> None:
        self.logger.info("Oriented R-CNN 插件正在卸载")

    def validate_params(
        self,
        params: dict[str, Any],
        *,
        context: TaskRuntimeContext | ExecutionBindingContext | None = None,
    ) -> None:
        del context
        self._runtime.validate_params(params)

    async def probe_runtime_capability(
        self,
        *,
        context: TaskRuntimeContext,
    ) -> RuntimeCapabilitySnapshot:
        del context
        return self._runtime.probe_runtime_capability()

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
        self.logger.info(f"开始准备 DOTA 数据集，样本数={len(samples)}")
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
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self.logger.info(f"开始训练，参数键={sorted(list(params.keys()))}")
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
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self.logger.info(f"开始评估，参数键={sorted(list(params.keys()))}")
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
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self.logger.info(
            f"执行选样预测 strategy={strategy}，未标注样本数={len(unlabeled_samples)}"
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
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        candidates = await self._runtime.predict_unlabeled_batch(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )
        top = candidates[0] if candidates else {}
        top_sample = str(top.get("sample_id") or "")
        top_score = float(top.get("score") or 0.0)
        self.logger.info(
            f"score 采样完成 strategy={strategy} 候选数={len(candidates)} "
            f"top_sample={top_sample or '-'} top_score={top_score:.6f}"
        )
        return candidates

    async def predict_samples_batch(
        self,
        workspace: WorkspaceProtocol,
        samples: list[dict[str, Any]],
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self.logger.info(f"执行直接推理，样本数={len(samples)}")
        return await self._runtime.predict_samples_batch(
            workspace=workspace,
            samples=samples,
            params=params,
            context=context,
        )

    async def stop(self, task_id: str) -> None:
        self.logger.info(f"收到 step {task_id} 停止请求")
        await self._runtime.stop(task_id)


__all__ = ["OrientedRCNNPlugin"]
