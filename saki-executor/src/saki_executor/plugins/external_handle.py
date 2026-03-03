"""Manifest-backed descriptor for external plugins.

`ExternalPluginDescriptor` only carries metadata and validation behaviors.
It does not implement execution methods.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from saki_plugin_sdk import StepRuntimeRequirements, parse_runtime_profiles
from saki_plugin_sdk.manifest import PluginManifest


class ExternalPluginDescriptor:
    def __init__(
        self,
        *,
        manifest: PluginManifest,
        plugin_dir: Path,
        python_path: Path,
    ) -> None:
        self._manifest = manifest
        self._plugin_dir = plugin_dir
        self._python_path = python_path

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @property
    def plugin_id(self) -> str:
        return self._manifest.plugin_id

    @property
    def version(self) -> str:
        return self._manifest.version

    @property
    def display_name(self) -> str:
        return self._manifest.display_name

    @property
    def supported_step_types(self) -> list[str]:
        return list(self._manifest.supported_step_types)

    @property
    def supported_strategies(self) -> list[str]:
        return list(self._manifest.supported_strategies)

    @property
    def supported_accelerators(self) -> list[str]:
        return list(self._manifest.supported_accelerators)

    @property
    def supports_auto_fallback(self) -> bool:
        return self._manifest.supports_auto_fallback

    @property
    def request_config_schema(self) -> dict[str, Any]:
        return dict(self._manifest.config_schema) if self._manifest.config_schema else {}

    @property
    def default_request_config(self) -> dict[str, Any]:
        return dict(self._manifest.default_config) if self._manifest.default_config else {}

    @property
    def plugin_dir(self) -> Path:
        return self._plugin_dir

    @property
    def python_path(self) -> Path:
        return self._python_path

    @property
    def entrypoint(self) -> str:
        return self._manifest.entrypoint

    @property
    def runtime_profiles(self) -> list[Any]:
        return parse_runtime_profiles(self._manifest.runtime_profiles)

    def resolve_config(
        self,
        mode: str,
        raw_config: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ):
        del mode
        from saki_plugin_sdk.config import ConfigSchema, PluginConfig

        return PluginConfig.resolve(
            schema=ConfigSchema.model_validate(self.request_config_schema or {}),
            raw_config=raw_config,
            context=context,
            validate=validate,
        )

    def validate_params(self, params: dict[str, Any], *, context: Any = None) -> None:
        context_payload = context.to_dict() if hasattr(context, "to_dict") and context else None
        self.resolve_config(
            mode=str(params.get("mode") or "manual"),
            raw_config=params,
            context=context_payload,
            validate=True,
        )

    def get_step_runtime_requirements(self, step_type: str) -> StepRuntimeRequirements:
        default = self._default_runtime_requirements(step_type)
        requirements_map = getattr(self._manifest, "step_runtime_requirements", {}) or {}
        if not isinstance(requirements_map, dict):
            return default

        normalized = str(step_type or "").strip().lower()
        raw = requirements_map.get(normalized)
        if raw is None:
            raw = requirements_map.get(step_type)
        if not isinstance(raw, dict):
            return default

        artifact_name = str(
            raw.get("primary_model_artifact_name", default.primary_model_artifact_name)
            or default.primary_model_artifact_name
        ).strip()
        return StepRuntimeRequirements(
            requires_prepare_data=bool(raw.get("requires_prepare_data", default.requires_prepare_data)),
            requires_trained_model=bool(raw.get("requires_trained_model", default.requires_trained_model)),
            primary_model_artifact_name=artifact_name,
        )

    @staticmethod
    def _default_runtime_requirements(step_type: str) -> StepRuntimeRequirements:
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
        if normalized == "predict":
            return StepRuntimeRequirements(
                requires_prepare_data=False,
                requires_trained_model=True,
                primary_model_artifact_name="best.pt",
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
