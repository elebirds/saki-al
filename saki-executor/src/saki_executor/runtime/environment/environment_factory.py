from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from saki_executor.runtime.environment.uv_profile_installer import sync_profile_env
from saki_executor.runtime.environment.venv_cache import VenvCacheKey, resolve_lock_hash
from saki_plugin_sdk import RuntimeProfileSpec


class EnvironmentFactory:
    def __init__(
        self,
        *,
        auto_sync: bool = True,
        mm_ext_auto_repair: bool = True,
        mm_ext_auto_repair_timeout_sec: int = 1200,
        cuda_toolchain_auto_align: bool = True,
        cuda_toolchain_auto_install_nvcc: bool = True,
        cuda_toolchain_align_timeout_sec: int = 300,
        cuda_toolchain_search_paths: list[Path] | None = None,
    ) -> None:
        self._auto_sync = bool(auto_sync)
        self._mm_ext_auto_repair = bool(mm_ext_auto_repair)
        self._mm_ext_auto_repair_timeout_sec = max(60, int(mm_ext_auto_repair_timeout_sec))
        self._cuda_toolchain_auto_align = bool(cuda_toolchain_auto_align)
        self._cuda_toolchain_auto_install_nvcc = bool(cuda_toolchain_auto_install_nvcc)
        self._cuda_toolchain_align_timeout_sec = max(30, int(cuda_toolchain_align_timeout_sec))
        self._cuda_toolchain_search_paths = list(cuda_toolchain_search_paths or [Path("/usr/local"), Path("/opt")])

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
            # 关键设计：profile 的 env 需要在 uv sync 阶段生效，否则会与 worker 运行时环境产生偏差。
            profile_env = {str(k): str(v) for k, v in dict(profile.env).items() if str(k).strip()}
            allowed_backends = {str(item or "").strip().lower() for item in list(profile.allowed_backends)}
            venv_dir.mkdir(parents=True, exist_ok=True)
            sync_profile_env(
                plugin_dir=plugin_dir,
                venv_dir=venv_dir,
                dependency_groups=list(profile.dependency_groups),
                profile_env=profile_env,
                is_cuda_profile="cuda" in allowed_backends,
                cuda_toolchain_auto_align=self._cuda_toolchain_auto_align,
                cuda_toolchain_auto_install_nvcc=self._cuda_toolchain_auto_install_nvcc,
                cuda_toolchain_align_timeout_sec=self._cuda_toolchain_align_timeout_sec,
                cuda_toolchain_search_paths=self._cuda_toolchain_search_paths,
                mm_ext_auto_repair=self._mm_ext_auto_repair,
                mm_ext_auto_repair_timeout_sec=self._mm_ext_auto_repair_timeout_sec,
            )
            marker.write_text(key.cache_id(), encoding="utf-8")

        if not python_path.exists():
            raise RuntimeError(
                f"PROFILE_UNSATISFIED: profile python interpreter not found "
                f"plugin_id={plugin_id} profile_id={profile_id} path={python_path}"
            )
        # Do not resolve symlink; keep venv interpreter semantics.
        return Path(os.path.abspath(python_path))
