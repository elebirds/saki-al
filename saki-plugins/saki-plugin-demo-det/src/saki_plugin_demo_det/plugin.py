from __future__ import annotations

from typing import Any

from saki_plugin_sdk import EventCallback, ExecutorPlugin, TrainOutput, Workspace
from saki_plugin_demo_det.internal import DemoDetectionInternal


class DemoDetectionPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        self._internal = DemoDetectionInternal()

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
    def request_config_schema(self) -> dict[str, Any]:
        return self._internal.config_schema()

    @property
    def default_request_config(self) -> dict[str, Any]:
        return self._internal.default_config()

    def validate_params(self, params: dict[str, Any]) -> None:
        self._internal.validate_params(params)

    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        await self._internal.prepare_data(workspace, labels, samples, annotations, dataset_ir, splits=splits)

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

    async def eval(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        return await self._internal.eval(workspace, params, emit)

    async def stop(self, step_id: str) -> None:
        await self._internal.stop(step_id)
