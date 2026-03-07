from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from loguru import logger

from saki_executor.plugins.external_handle import ExternalPluginDescriptor


class PluginRegistry:
    """Registry that discovers external plugins from a directory of plugin packages."""

    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}

    def register(self, plugin: Any) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> Any | None:
        return self._plugins.get(plugin_id)

    def all(self) -> list[Any]:
        return list(self._plugins.values())

    def ensure_worker_loadable(self, plugin_id: str) -> None:
        handle = self._plugins.get(plugin_id)
        if handle is None:
            raise RuntimeError(f"插件注册表中未找到插件: {plugin_id}")

    def worker_loadable(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def discover_plugins(self, plugins_dir: str | Path) -> None:
        """Scan *plugins_dir* for sub-directories containing ``plugin.yml``."""
        from saki_plugin_sdk.manifest import PluginManifest

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
                handle = ExternalPluginDescriptor(
                    manifest=manifest,
                    plugin_dir=candidate,
                    python_path=Path(sys.executable),
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
