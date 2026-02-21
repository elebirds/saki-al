from saki_executor.plugins.base import ExecutorPlugin
from saki_executor.plugins.factory import is_plugin_loadable, load_builtin_plugins


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ExecutorPlugin] = {}

    def register(self, plugin: ExecutorPlugin) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> ExecutorPlugin | None:
        return self._plugins.get(plugin_id)

    def all(self) -> list[ExecutorPlugin]:
        return list(self._plugins.values())

    def ensure_worker_loadable(self, plugin_id: str) -> None:
        if not is_plugin_loadable(plugin_id):
            raise RuntimeError(f"plugin is not loadable in worker process: {plugin_id}")

    def worker_loadable(self, plugin_id: str) -> bool:
        return is_plugin_loadable(plugin_id)

    def load_builtin(self) -> None:
        for plugin in load_builtin_plugins():
            self.register(plugin)
