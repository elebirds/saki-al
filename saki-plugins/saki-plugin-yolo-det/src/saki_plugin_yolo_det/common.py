from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def to_yolo_device(binding_backend: str, binding_device_spec: str) -> Any:
    backend = str(binding_backend or "").strip().lower()
    spec = str(binding_device_spec or "").strip().lower()
    if backend == "cuda":
        if spec.startswith("cuda:"):
            return spec.split(":", 1)[1] or "0"
        return spec or "0"
    if backend == "mps":
        return "mps"
    return "cpu"


def infer_image_hw(path: Path) -> tuple[int, int]:
    if Image is None:
        raise RuntimeError("Pillow is required for yolo_det_v1 plugin")
    with Image.open(path) as img:
        w, h = img.size
        return h, w
