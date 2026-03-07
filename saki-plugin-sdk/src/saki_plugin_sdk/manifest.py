"""Plugin manifest (``plugin.yml``) parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
import yaml

from saki_plugin_sdk.profile_spec import parse_runtime_profiles


class PluginManifest(BaseModel):
    """Describes a plugin's static metadata – loaded from ``plugin.yml``."""

    plugin_id: str
    version: str = "0.0.0"
    display_name: str = ""
    sdk_version: str = ">=4.0.0"

    supported_task_types: list[str] = Field(default_factory=list)
    supported_strategies: list[str] = Field(default_factory=list)
    supported_accelerators: list[str] = Field(default_factory=lambda: ["cpu"])
    supports_auto_fallback: bool = True
    task_runtime_requirements: dict[str, dict[str, Any]] = Field(default_factory=dict)
    runtime_profiles: list[dict[str, Any]] = Field(default_factory=list)

    config_schema: dict[str, Any] = Field(default_factory=dict)

    entrypoint: str = ""
    """Module path used to start the plugin worker, e.g. ``saki_plugin_demo_det.worker:main``."""

    @field_validator("runtime_profiles", mode="after")
    @classmethod
    def validate_runtime_profiles(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        profiles = parse_runtime_profiles(value)
        return [item.to_dict() for item in profiles]

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_default_config(cls, data: Any) -> Any:
        if isinstance(data, dict) and "default_config" in data:
            raise ValueError("plugin.yml no longer supports default_config; use config_schema.fields[*].default")
        return data

    @classmethod
    def from_yaml(cls, path: Path) -> "PluginManifest":
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"plugin.yml must be a YAML mapping: {path}")
        return cls.model_validate(data)
