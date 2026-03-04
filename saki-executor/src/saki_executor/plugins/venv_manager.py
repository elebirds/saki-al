"""Plugin virtual environment manager.

Ensures each external plugin directory has a synced venv via ``uv sync``,
and exposes the path to the plugin's Python interpreter.
"""

from __future__ import annotations

import os
from pathlib import Path

from saki_executor.core.config import settings
from saki_executor.runtime.environment.environment_factory import EnvironmentFactory
from saki_plugin_sdk.profile_spec import RuntimeProfileSpec


def ensure_plugin_venv(plugin_dir: Path, *, auto_sync: bool = True) -> Path:
    return ensure_plugin_venv_for_profile(
        plugin_dir=plugin_dir,
        plugin_id=Path(plugin_dir).name,
        plugin_version="0.0.0",
        profile=RuntimeProfileSpec(
            id="cpu",
            priority=100,
            when="host.backends.includes('cpu')",
            dependency_groups=["profile-cpu"],
            allowed_backends=["cpu"],
        ),
        auto_sync=auto_sync,
    )


def ensure_plugin_venv_for_profile(
    *,
    plugin_dir: Path,
    plugin_id: str,
    plugin_version: str,
    profile: RuntimeProfileSpec,
    auto_sync: bool = True,
) -> Path:
    plugin_dir = Path(os.path.abspath(plugin_dir))
    factory = EnvironmentFactory(
        auto_sync=auto_sync,
        mm_ext_auto_repair=bool(settings.PLUGIN_MM_EXT_AUTO_REPAIR),
        mm_ext_auto_repair_timeout_sec=int(settings.PLUGIN_MM_EXT_AUTO_REPAIR_TIMEOUT_SEC),
    )
    return factory.ensure_profile_python(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        plugin_dir=plugin_dir,
        profile=profile,
    )
