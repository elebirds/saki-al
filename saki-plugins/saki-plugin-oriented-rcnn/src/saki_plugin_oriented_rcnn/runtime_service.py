from __future__ import annotations

import threading
from typing import Any

from saki_plugin_sdk import (
    EventCallback,
    ExecutionBindingContext,
    RuntimeCapabilitySnapshot,
    TrainOutput,
    WorkspaceProtocol,
)

from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.eval_service import OrientedRCNNEvalService
from saki_plugin_oriented_rcnn.predict_service import OrientedRCNNPredictService
from saki_plugin_oriented_rcnn.prepare_pipeline import parse_split_params, prepare_dota_dataset
from saki_plugin_oriented_rcnn.runtime_probe_torch import probe_torch_runtime_capability
from saki_plugin_oriented_rcnn.train_service import OrientedRCNNTrainService


class OrientedRCNNRuntimeService:
    def __init__(self) -> None:
        self._stop_flag = threading.Event()
        self._config_service = OrientedRCNNConfigService()
        self._train_service = OrientedRCNNTrainService(
            stop_flag=self._stop_flag,
            config_service=self._config_service,
        )
        self._eval_service = OrientedRCNNEvalService(
            stop_flag=self._stop_flag,
            config_service=self._config_service,
        )
        self._predict_service = OrientedRCNNPredictService(
            stop_flag=self._stop_flag,
            config_service=self._config_service,
        )

    def validate_params(self, params: dict[str, Any]) -> None:
        self._config_service.validate_params(params)

    def probe_runtime_capability(self) -> RuntimeCapabilitySnapshot:
        return probe_torch_runtime_capability()

    async def prepare_data(
        self,
        *,
        workspace: WorkspaceProtocol,
        labels: list[dict[str, Any]],
        samples: list[dict[str, Any]],
        annotations: list[dict[str, Any]],
        dataset_ir: Any,
        splits: dict[str, list[dict[str, Any]]] | None = None,
        context: ExecutionBindingContext,
    ) -> None:
        del annotations, context
        split_seed, val_ratio = parse_split_params(splits)
        _ = prepare_dota_dataset(
            workspace=workspace,
            labels=labels,
            samples=samples,
            dataset_ir=dataset_ir,
            splits=splits,
            split_seed=split_seed,
            val_ratio=val_ratio,
        )

    async def train(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._stop_flag.clear()
        return await self._train_service.train(
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def eval(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._stop_flag.clear()
        return await self._eval_service.eval(
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def predict_unlabeled(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        return await self._predict_service.predict_unlabeled(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def predict_unlabeled_batch(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        return await self._predict_service.predict_unlabeled_batch(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def stop(self, step_id: str) -> None:
        del step_id
        self._stop_flag.set()
