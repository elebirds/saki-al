from __future__ import annotations

import pytest

from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService


def test_resolve_config_defaults_and_ranges() -> None:
    service = OrientedRCNNConfigService()
    cfg = service.resolve_config(
        {
            "epochs": 0,
            "batch": -1,
            "imgsz": 100,
            "model_source": "preset",
            "model_preset": "oriented-rcnn-le90_r50_fpn_1x_dota",
            "predict_geometry_mode": "auto",
        }
    )

    assert cfg.epochs >= 1
    assert cfg.batch >= 1
    assert cfg.imgsz >= 256
    assert cfg.model_source == "preset"
    assert cfg.model_preset == "oriented-rcnn-le90_r50_fpn_1x_dota"
    assert cfg.deterministic is True
    assert cfg.aug_iou_iou_mode == "obb"
    assert cfg.aug_iou_boundary_d == 3


def test_resolve_config_rejects_missing_custom_ref() -> None:
    service = OrientedRCNNConfigService()
    with pytest.raises(ValueError, match="model_custom_ref"):
        service.resolve_config(
            {
                "model_source": "custom_local",
                "model_custom_ref": "",
            }
        )


def test_validate_params_accepts_preset() -> None:
    service = OrientedRCNNConfigService()
    service.validate_params(
        {
            "model_source": "preset",
            "model_preset": "oriented-rcnn-le90_r50_fpn_1x_dota",
        }
    )
