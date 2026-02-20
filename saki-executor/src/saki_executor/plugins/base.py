from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from saki_executor.steps.workspace import Workspace


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
    def supported_step_types(self) -> list[str]:
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
            dataset_ir: Any,
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
    async def stop(self, step_id: str) -> None:
        pass
