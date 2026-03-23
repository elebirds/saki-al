from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from obb_baseline.registry import load_model_registry


def _valid_models_config() -> dict[str, object]:
    return {
        "models": {
            "yolo11m_obb": {
                "runner": "yolo",
                "env": "yolo",
                "data_view": "yolo_obb",
                "preset": "yolo11m-obb",
            },
            "oriented_rcnn_r50": {
                "runner": "mmrotate",
                "env": "mmrotate",
                "data_view": "dota",
                "preset": "oriented-rcnn-r50-fpn",
            },
            "roi_transformer_r50": {
                "runner": "mmrotate",
                "env": "mmrotate",
                "data_view": "dota",
                "preset": "roi-transformer-r50-fpn",
            },
            "r3det_r50": {
                "runner": "mmrotate",
                "env": "mmrotate",
                "data_view": "dota",
                "preset": "r3det-r50-fpn",
            },
            "rtmdet_rotated_m": {
                "runner": "mmrotate",
                "env": "mmrotate",
                "data_view": "dota",
                "preset": "rtmdet-rotated-m",
            },
        }
    }


def test_load_model_registry_reads_5_models_from_models_yaml() -> None:
    config_path = Path(__file__).resolve().parents[1] / "configs" / "models.yaml"

    registry = load_model_registry(config_path)

    assert set(registry) == {
        "yolo11m_obb",
        "oriented_rcnn_r50",
        "roi_transformer_r50",
        "r3det_r50",
        "rtmdet_rotated_m",
    }
    assert len(registry) == 5
    assert registry["yolo11m_obb"].runner_name == "yolo"
    assert registry["yolo11m_obb"].env_name == "yolo"
    assert registry["yolo11m_obb"].data_view == "yolo_obb"
    assert registry["yolo11m_obb"].preset == "yolo11m-obb"
    assert registry["oriented_rcnn_r50"].runner_name == "mmrotate"
    assert registry["oriented_rcnn_r50"].data_view == "dota"


def test_load_model_registry_rejects_invalid_runner_and_data_view(
    tmp_path: Path,
) -> None:
    payload_runner = _valid_models_config()
    payload_runner["models"]["yolo11m_obb"]["runner"] = "unknown_runner"
    config_runner = tmp_path / "models_invalid_runner.yaml"
    config_runner.write_text(yaml.safe_dump(payload_runner), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported runner 'unknown_runner'"):
        load_model_registry(config_runner)

    payload_data_view = _valid_models_config()
    payload_data_view["models"]["yolo11m_obb"]["data_view"] = "unknown_view"
    config_data_view = tmp_path / "models_invalid_data_view.yaml"
    config_data_view.write_text(yaml.safe_dump(payload_data_view), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported data_view 'unknown_view'"):
        load_model_registry(config_data_view)


def test_load_model_registry_rejects_mixed_type_model_keys(
    tmp_path: Path,
) -> None:
    payload = _valid_models_config()
    payload["models"].pop("rtmdet_rotated_m")
    payload["models"][101] = {
        "runner": "mmrotate",
        "env": "mmrotate",
        "data_view": "dota",
        "preset": "rtmdet-rotated-m",
    }
    config_path = tmp_path / "models_mixed_keys.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="model names must be strings"):
        load_model_registry(config_path)


def test_load_model_registry_rejects_unknown_model_fields(
    tmp_path: Path,
) -> None:
    payload = _valid_models_config()
    payload["models"]["yolo11m_obb"]["extra"] = "forbidden"
    config_path = tmp_path / "models_unknown_field.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        load_model_registry(config_path)


def test_load_model_registry_rejects_invalid_env(
    tmp_path: Path,
) -> None:
    payload = _valid_models_config()
    payload["models"]["yolo11m_obb"]["env"] = "invalid_env"
    config_path = tmp_path / "models_invalid_env.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported env 'invalid_env'"):
        load_model_registry(config_path)
