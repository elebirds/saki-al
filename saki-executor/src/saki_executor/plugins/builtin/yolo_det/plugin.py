from __future__ import annotations

from typing import Any

from saki_executor.steps.workspace import Workspace
from saki_executor.plugins.base import EventCallback, ExecutorPlugin, TrainOutput
from saki_executor.plugins.builtin.yolo_det.internal import (
    YoloDetectionInternal,
    _infer_image_hw as _internal_infer_image_hw,
)

# Keep this symbol on module-level for backward-compatible tests/monkeypatch.
_infer_image_hw = _internal_infer_image_hw


class YoloDetectionPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        self._internal = YoloDetectionInternal()

    @property
    def plugin_id(self) -> str:
        return self._internal.plugin_id

    @property
    def version(self) -> str:
        return self._internal.version

    @property
    def display_name(self) -> str:
        return self._internal.display_name

    @property
    def supported_step_types(self) -> list[str]:
        return self._internal.supported_step_types

    @property
    def supported_strategies(self) -> list[str]:
        return self._internal.supported_strategies

    @property
    def supported_accelerators(self) -> list[str]:
        return self._internal.supported_accelerators

    @property
    def supports_auto_fallback(self) -> bool:
        return self._internal.supports_auto_fallback

    @property
    def request_config_schema(self) -> dict[str, Any]:
        return self._internal.request_config_schema

    @property
    def default_request_config(self) -> dict[str, Any]:
        return self._internal.default_request_config

    def validate_params(self, params: dict[str, Any]) -> None:
        self._internal.validate_params(params)

    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
    ) -> None:
        await self._internal.prepare_data(
            workspace=workspace,
            labels=labels,
            samples=samples,
            annotations=annotations,
            dataset_ir=dataset_ir,
            infer_image_hw=_infer_image_hw,
        )

    async def train(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        return await self._internal.train(workspace, params, emit)

    async def predict_unlabeled(
            self,
            workspace: Workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self._internal.predict_unlabeled(workspace, unlabeled_samples, strategy, params)

    async def predict_unlabeled_batch(
            self,
            workspace: Workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self._internal.predict_unlabeled_batch(workspace, unlabeled_samples, strategy, params)

    async def stop(self, step_id: str) -> None:
        await self._internal.stop(step_id)

    def _resolve_split_config(self, workspace: Workspace) -> tuple[int, float]:
        return self._internal._resolve_split_config(workspace)  # noqa: SLF001


__all__ = ["YoloDetectionPlugin", "_infer_image_hw"]
