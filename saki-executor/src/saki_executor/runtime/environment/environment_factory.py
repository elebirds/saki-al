from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from saki_executor.runtime.environment.uv_profile_installer import sync_profile_env
from saki_executor.runtime.environment.venv_cache import VenvCacheKey, resolve_lock_hash
from saki_plugin_sdk import RuntimeProfileSpec


class EnvironmentFactory:
    def __init__(self, *, auto_sync: bool = True) -> None:
        self._auto_sync = bool(auto_sync)

    def ensure_profile_python(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        plugin_dir: Path,
        profile: RuntimeProfileSpec,
    ) -> Path:
        profile_id = str(profile.id or "").strip()
        if not profile_id:
            raise RuntimeError("runtime profile id is required")

        venv_dir = plugin_dir / f".venv-{profile_id}"
        python_path = venv_dir / "bin" / "python"
        key = VenvCacheKey(
            plugin_id=str(plugin_id),
            plugin_version=str(plugin_version),
            profile_id=profile_id,
            lock_hash=resolve_lock_hash(plugin_dir),
            py_version=f"{sys.version_info.major}.{sys.version_info.minor}",
            platform_arch=f"{platform.system().lower()}-{platform.machine().lower()}",
        )
        marker = venv_dir / ".profile_cache_id"
        marker_id = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
        should_sync = (
            self._auto_sync
            and (not python_path.exists() or marker_id != key.cache_id())
            and (plugin_dir / "pyproject.toml").exists()
        )
        if should_sync:
            venv_dir.mkdir(parents=True, exist_ok=True)
            sync_profile_env(
                plugin_dir=plugin_dir,
                venv_dir=venv_dir,
                dependency_groups=list(profile.dependency_groups),
            )
            marker.write_text(key.cache_id(), encoding="utf-8")

        if not python_path.exists():
            raise RuntimeError(
                f"PROFILE_UNSATISFIED: profile python interpreter not found "
                f"plugin_id={plugin_id} profile_id={profile_id} path={python_path}"
            )
        # Do not resolve symlink; keep venv interpreter semantics.
        return Path(os.path.abspath(python_path))
