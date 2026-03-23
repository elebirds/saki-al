from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_ALLOWED_MODEL_NAMES = {
    "yolo11m_obb",
    "oriented_rcnn_r50",
    "roi_transformer_r50",
    "r3det_r50",
    "rtmdet_rotated_m",
}
_ALLOWED_RUNNERS = {"mmrotate", "yolo"}
_ALLOWED_DATA_VIEWS = {"dota", "yolo_obb"}


@dataclass(frozen=True)
class ModelSpec:
    model_name: str
    runner_name: str
    env_name: str
    data_view: str
    preset: str


def _require_string(value: object, *, field_name: str, model_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"model '{model_name}' field '{field_name}' must be a non-empty string")
    return value


def load_model_registry(path: Path) -> dict[str, ModelSpec]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"failed to read model registry: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"failed to parse yaml: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("model registry yaml root must be a mapping")

    models_raw = payload.get("models")
    if not isinstance(models_raw, dict):
        raise ValueError("model registry yaml must contain mapping key 'models'")

    names = set(models_raw.keys())
    if names != _ALLOWED_MODEL_NAMES:
        raise ValueError(
            "model registry must contain exactly these model names: "
            f"{sorted(_ALLOWED_MODEL_NAMES)}; got: {sorted(names)}",
        )

    registry: dict[str, ModelSpec] = {}
    for model_name in sorted(_ALLOWED_MODEL_NAMES):
        item = models_raw.get(model_name)
        if not isinstance(item, dict):
            raise ValueError(f"model '{model_name}' config must be a mapping")

        runner_name = _require_string(item.get("runner"), field_name="runner", model_name=model_name)
        env_name = _require_string(item.get("env"), field_name="env", model_name=model_name)
        data_view = _require_string(item.get("data_view"), field_name="data_view", model_name=model_name)
        preset = _require_string(item.get("preset"), field_name="preset", model_name=model_name)

        if runner_name not in _ALLOWED_RUNNERS:
            raise ValueError(
                f"model '{model_name}' has unsupported runner '{runner_name}', "
                f"allowed: {sorted(_ALLOWED_RUNNERS)}",
            )
        if data_view not in _ALLOWED_DATA_VIEWS:
            raise ValueError(
                f"model '{model_name}' has unsupported data_view '{data_view}', "
                f"allowed: {sorted(_ALLOWED_DATA_VIEWS)}",
            )

        registry[model_name] = ModelSpec(
            model_name=model_name,
            runner_name=runner_name,
            env_name=env_name,
            data_view=data_view,
            preset=preset,
        )

    return registry
