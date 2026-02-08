from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any, Callable, Awaitable

from saki_executor.jobs.workspace import Workspace


EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class TrainArtifact:
    kind: str
    name: str
    path: Path
    content_type: str = "application/octet-stream"
    meta: dict[str, Any] | None = None
    required: bool = False


@dataclass
class TrainOutput:
    metrics: dict[str, Any]
    artifacts: list[TrainArtifact]


class ExecutorPlugin(ABC):
    @property
    @abstractmethod
    def plugin_id(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @property
    def display_name(self) -> str:
        return self.plugin_id

    @property
    @abstractmethod
    def supported_job_types(self) -> list[str]:
        pass

    @property
    @abstractmethod
    def supported_strategies(self) -> list[str]:
        pass

    @property
    def request_config_schema(self) -> dict[str, Any]:
        return {}

    @property
    def default_request_config(self) -> dict[str, Any]:
        return {}

    @property
    def supported_accelerators(self) -> list[str]:
        return ["cpu"]

    @property
    def supports_auto_fallback(self) -> bool:
        return True

    @abstractmethod
    def validate_params(self, params: dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
    ) -> None:
        pass

    @abstractmethod
    async def train(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        pass

    @abstractmethod
    async def predict_unlabeled(
            self,
            workspace: Workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        pass

    async def predict_unlabeled_batch(
            self,
            workspace: Workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self.predict_unlabeled(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
        )

    @abstractmethod
    async def stop(self, job_id: str) -> None:
        pass

    async def select_simulation_subset(
            self,
            *,
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            ratio: float,
            iteration: int,
            params: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        del iteration, params
        if not samples or not annotations:
            return samples, annotations

        sample_map = {str(item.get("id") or ""): item for item in samples if item.get("id")}
        labeled_sample_ids = sorted(
            {
                str(item.get("sample_id") or "")
                for item in annotations
                if str(item.get("sample_id") or "") in sample_map
            }
        )
        if not labeled_sample_ids:
            return samples, annotations

        target = max(1, min(len(labeled_sample_ids), ceil(len(labeled_sample_ids) * ratio)))
        selected_ids = set(labeled_sample_ids[:target])
        selected_samples = [sample_map[sample_id] for sample_id in labeled_sample_ids if sample_id in selected_ids]
        selected_annotations = [
            item for item in annotations
            if str(item.get("sample_id") or "") in selected_ids
        ]
        return selected_samples, selected_annotations
