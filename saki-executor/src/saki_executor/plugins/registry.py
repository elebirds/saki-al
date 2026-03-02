from __future__ import annotations

from pathlib import Path

from loguru import logger

from saki_executor.plugins.external_handle import ExternalPluginHandle


class PluginRegistry:
    """Registry that discovers external plugins from a directory of plugin packages."""

    def __init__(self) -> None:
        self._plugins: dict[str, ExternalPluginHandle] = {}

    def register(self, plugin: ExternalPluginHandle) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> ExternalPluginHandle | None:
        return self._plugins.get(plugin_id)

    def all(self) -> list[ExternalPluginHandle]:
        return list(self._plugins.values())

    def ensure_worker_loadable(self, plugin_id: str) -> None:
        handle = self._plugins.get(plugin_id)
        if handle is None:
            raise RuntimeError(f"plugin not found in registry: {plugin_id}")
        # External plugins are always loadable as long as venv can be resolved.

    def worker_loadable(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def discover_plugins(self, plugins_dir: str | Path, *, auto_sync: bool = True) -> None:
        """Scan *plugins_dir* for sub-directories containing ``plugin.yml``."""
        from saki_plugin_sdk.manifest import PluginManifest
        from saki_executor.plugins.venv_manager import ensure_plugin_venv

        root = Path(plugins_dir)
        if not root.is_dir():
            logger.warning("插件目录不存在：{}", root)
            return

        for candidate in sorted(root.iterdir()):
            yml = candidate / "plugin.yml"
            if not yml.is_file():
                continue
            try:
                manifest = PluginManifest.from_yaml(yml)
                python_path = ensure_plugin_venv(candidate, auto_sync=auto_sync)
                handle = ExternalPluginHandle(
                    manifest=manifest,
                    plugin_dir=candidate,
                    python_path=python_path,
                )
                self.register(handle)
                logger.info(
                    "发现插件：插件ID={} 版本={} 目录={}",
                    manifest.plugin_id,
                    manifest.version,
                    candidate,
                )
            except Exception:
                logger.exception("加载插件失败，目录={}", candidate)
