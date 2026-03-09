from __future__ import annotations

from typing import Any

from saki_plugin_oriented_rcnn.plugin import OrientedRCNNPlugin


def test_plugin_init_config_log_uses_request_schema_property() -> None:
    plugin = OrientedRCNNPlugin()

    text = plugin._build_init_config_log()

    assert "插件初始化配置摘要" in text
    assert "aug_iou_iou_mode 默认=obb" in text
    assert "aug_iou_boundary_d 默认=3 范围=[1,128]" in text


class _LegacySchemaPlugin(OrientedRCNNPlugin):
    def request_config_schema(self) -> dict[str, Any]:
        return {
            "fields": [
                {
                    "key": "aug_iou_iou_mode",
                    "default": "rect",
                    "options": [{"value": "rect"}, {"value": "obb"}],
                },
                {
                    "key": "aug_iou_boundary_d",
                    "default": 7,
                    "props": {"min": 2, "max": 64},
                },
                {
                    "key": "aug_iou_enabled_augs",
                    "default": ["identity", "rot90"],
                },
            ]
        }


def test_plugin_init_config_log_accepts_callable_request_schema() -> None:
    plugin = _LegacySchemaPlugin()

    text = plugin._build_init_config_log()

    assert "aug_iou_iou_mode 默认=rect 可选=rect/obb" in text
    assert "aug_iou_boundary_d 默认=7 范围=[2,64]" in text
    assert "aug_iou_enabled_augs 默认项数=2" in text
