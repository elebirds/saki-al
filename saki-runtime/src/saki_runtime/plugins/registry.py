import importlib
from typing import Any, Dict, List, Optional

from loguru import logger

from saki_runtime.plugins.base import PluginBase


class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, PluginBase] = {}

    def register(self, plugin: PluginBase) -> None:
        if plugin.id in self._plugins:
            logger.warning(f"Plugin {plugin.id} already registered, overwriting.")
        self._plugins[plugin.id] = plugin
        logger.info(f"Registered plugin: {plugin.id} v{plugin.version}")

    def get(self, plugin_id: str) -> Optional[PluginBase]:
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": p.id,
                "version": p.version,
                "capabilities": p.capabilities,
            }
            for p in self._plugins.values()
        ]

    def load_builtin_plugins(self) -> None:
        try:
            from saki_runtime.plugins.builtin.yolo_det_v1.plugin import YoloDetPlugin
            self.register(YoloDetPlugin())
        except ImportError as e:
            logger.error(f"Failed to load builtin plugin yolo_det_v1: {e}")

# Global registry
registry = PluginRegistry()
