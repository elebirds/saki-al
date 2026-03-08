from __future__ import annotations

import pytest

from saki_plugin_sdk.config import ConfigSchema, PluginConfig
from saki_plugin_sdk.exceptions import PluginValidationError


def _schema() -> ConfigSchema:
    return ConfigSchema.model_validate(
        {
            "fields": [
                {
                    "key": "aug_iou_enabled_augs",
                    "label": "aug_iou 增强项",
                    "type": "multi_select",
                    "required": True,
                    "default": ["identity", "hflip"],
                    "options": [
                        {"label": "identity", "value": "identity"},
                        {"label": "hflip", "value": "hflip"},
                        {"label": "vflip", "value": "vflip"},
                    ],
                }
            ]
        }
    )


def test_multi_select_accepts_valid_array() -> None:
    config = PluginConfig.resolve(
        schema=_schema(),
        raw_config={"aug_iou_enabled_augs": ["vflip", "identity"]},
        validate=True,
    )
    assert list(config.aug_iou_enabled_augs) == ["vflip", "identity"]


def test_multi_select_rejects_scalar_value() -> None:
    with pytest.raises(PluginValidationError, match="must be an array"):
        PluginConfig.resolve(
            schema=_schema(),
            raw_config={"aug_iou_enabled_augs": "identity"},
            validate=True,
        )


def test_multi_select_rejects_invalid_options() -> None:
    with pytest.raises(PluginValidationError, match="invalid options"):
        PluginConfig.resolve(
            schema=_schema(),
            raw_config={"aug_iou_enabled_augs": ["identity", "custom_op"]},
            validate=True,
        )


def test_multi_select_required_rejects_empty_array() -> None:
    with pytest.raises(PluginValidationError, match="is required"):
        PluginConfig.resolve(
            schema=_schema(),
            raw_config={"aug_iou_enabled_augs": []},
            validate=True,
        )
