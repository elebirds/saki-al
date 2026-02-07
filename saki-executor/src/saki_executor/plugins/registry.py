from saki_executor.plugins.base import ExecutorPlugin
from saki_executor.plugins.builtin.demo_det.plugin import DemoDetectionPlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ExecutorPlugin] = {}

    def register(self, plugin: ExecutorPlugin) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> ExecutorPlugin | None:
        return self._plugins.get(plugin_id)

    def all(self) -> list[ExecutorPlugin]:
        return list(self._plugins.values())

    def load_builtin(self) -> None:
        self.register(DemoDetectionPlugin())
