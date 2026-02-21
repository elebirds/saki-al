from __future__ import annotations

from collections.abc import Callable

from saki_executor.plugins.base import ExecutorPlugin
from saki_executor.plugins.builtin.demo_det.plugin import DemoDetectionPlugin
from saki_executor.plugins.builtin.yolo_det.plugin import YoloDetectionPlugin

PluginBuilder = Callable[[], ExecutorPlugin]

_PLUGIN_BUILDERS: dict[str, PluginBuilder] = {
    "yolo_det_v1": YoloDetectionPlugin,
    "demo_det_v1": DemoDetectionPlugin,
}


def available_plugin_ids() -> list[str]:
    return list(_PLUGIN_BUILDERS.keys())


def is_plugin_loadable(plugin_id: str) -> bool:
    return str(plugin_id or "").strip() in _PLUGIN_BUILDERS


def create_plugin(plugin_id: str) -> ExecutorPlugin:
    key = str(plugin_id or "").strip()
    builder = _PLUGIN_BUILDERS.get(key)
    if builder is None:
        raise ValueError(f"plugin is not loadable in worker process: {plugin_id}")
    return builder()


def load_builtin_plugins() -> list[ExecutorPlugin]:
    return [create_plugin(plugin_id) for plugin_id in available_plugin_ids()]
