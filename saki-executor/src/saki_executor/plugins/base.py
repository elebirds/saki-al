from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

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


@dataclass(frozen=True)
class StepRuntimeRequirements:
    requires_prepare_data: bool
    requires_trained_model: bool
    primary_model_artifact_name: str = "best.pt"


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

    def resolve_config(
        self,
        mode: str,
        raw_config: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> "PluginConfig":
        """Build a :class:`PluginConfig` from defaults + user overrides.

        Merges ``default_request_config`` with *raw_config*, resolves
        any conditional-default lists, coerces values to their
        schema-declared types, and (optionally) validates constraints.
        """
        from saki_plugin_sdk.config import ConfigSchema, PluginConfig

        return PluginConfig.resolve(
            schema=ConfigSchema.model_validate(self.request_config_schema or {}),
            raw_config=raw_config,
            context=context,
            validate=validate,
        )

    @property
    def supported_accelerators(self) -> list[str]:
        return ["cpu"]

    @property
    def supports_auto_fallback(self) -> bool:
        return True

    def validate_params(self, params: dict[str, Any]) -> None:
        del params

    def get_step_runtime_requirements(self, step_type: str) -> StepRuntimeRequirements:
        normalized = str(step_type or "").strip().lower()
        if normalized == "train":
            return StepRuntimeRequirements(
                requires_prepare_data=True,
                requires_trained_model=False,
                primary_model_artifact_name="best.pt",
            )
        if normalized == "score":
            return StepRuntimeRequirements(
                requires_prepare_data=False,
                requires_trained_model=True,
                primary_model_artifact_name="best.pt",
            )
        if normalized == "eval":
            return StepRuntimeRequirements(
                requires_prepare_data=True,
                requires_trained_model=True,
                primary_model_artifact_name="best.pt",
            )
        if normalized == "export":
            return StepRuntimeRequirements(
                requires_prepare_data=False,
                requires_trained_model=True,
                primary_model_artifact_name="best.pt",
            )
        if normalized == "upload_artifact":
            return StepRuntimeRequirements(
                requires_prepare_data=False,
                requires_trained_model=False,
                primary_model_artifact_name="",
            )
        if normalized == "custom":
            return StepRuntimeRequirements(
                requires_prepare_data=True,
                requires_trained_model=False,
                primary_model_artifact_name="best.pt",
            )
        return StepRuntimeRequirements(
            requires_prepare_data=True,
            requires_trained_model=False,
            primary_model_artifact_name="best.pt",
        )

    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        del workspace, labels, samples, annotations, dataset_ir, splits

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

    async def eval(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        del workspace, params, emit
        raise NotImplementedError("eval step is not implemented by this plugin")

    async def export(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        del workspace, params, emit
        raise NotImplementedError("export step is not implemented by this plugin")

    async def upload_artifact(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        del workspace, params, emit
        raise NotImplementedError("upload_artifact step is not implemented by this plugin")

    async def stop(self, step_id: str) -> None:
        del step_id
