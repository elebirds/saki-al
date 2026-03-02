"""Plugin manifest (``plugin.yml``) parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
import yaml


class PluginManifest(BaseModel):
    """Describes a plugin's static metadata – loaded from ``plugin.yml``."""

    plugin_id: str
    version: str = "0.0.0"
    display_name: str = ""
    sdk_version: str = ">=2.0.0"

    supported_step_types: list[str] = Field(default_factory=list)
    supported_strategies: list[str] = Field(default_factory=list)
    supported_accelerators: list[str] = Field(default_factory=lambda: ["cpu"])
    supports_auto_fallback: bool = True
    step_runtime_requirements: dict[str, dict[str, Any]] = Field(default_factory=dict)

    config_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)

    entrypoint: str = ""
    """Module path used to start the plugin worker, e.g. ``saki_plugin_demo_det.worker:main``."""

    @classmethod
    def from_yaml(cls, path: Path) -> "PluginManifest":
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"plugin.yml must be a YAML mapping: {path}")
        return cls.model_validate(data)
