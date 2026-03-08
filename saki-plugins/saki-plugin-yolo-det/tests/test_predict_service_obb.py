from __future__ import annotations

import math
import threading

import pytest

from saki_plugin_yolo_det.config_service import YoloConfigService
from saki_plugin_yolo_det.predict_service import YoloPredictService


class _Array:
    def __init__(self, values):
        self._values = values

    def cpu(self):
        return self

    def tolist(self):
        return list(self._values)


class _ObbBoxes:
    def __init__(self):
        self.cls = _Array([1])
        self.conf = _Array([0.9])
        self.xyxyxyxy = _Array([[[1.0, 2.0], [5.0, 2.0], [5.0, 4.0], [1.0, 4.0]]])

    def __len__(self):
        return 1


class _ObbResult:
    def __init__(self):
        self.obb = _ObbBoxes()
        self.names = {1: "car"}


def _build_service() -> YoloPredictService:
    return YoloPredictService(
        stop_flag=threading.Event(),
        config_service=YoloConfigService(),
        load_yolo=lambda: None,
    )


def test_extract_predictions_obb_includes_qbox_and_rect() -> None:
    service = _build_service()
    rows = service._extract_predictions(_ObbResult())
    assert len(rows) == 1
    row = rows[0]
    assert row["class_index"] == 1
    assert row["class_name"] == "car"
    assert row["confidence"] == pytest.approx(0.9)
    assert row["qbox"] == pytest.approx((1.0, 2.0, 5.0, 2.0, 5.0, 4.0, 1.0, 4.0))
    rect = (row.get("geometry") or {}).get("rect") or {}
    assert rect.get("x") == pytest.approx(1.0)
    assert rect.get("y") == pytest.approx(2.0)
    assert rect.get("width") == pytest.approx(4.0)
    assert rect.get("height") == pytest.approx(2.0)


def test_inverse_aug_box_flips_qbox_hflip_and_rebuilds_rect() -> None:
    service = _build_service()
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": (1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0),
        "geometry": {"rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 1.0}},
    }
    restored = service._inverse_aug_box(name="hflip", row=row, width=10, height=8)
    assert restored["qbox"] == pytest.approx((9.0, 1.0, 7.0, 1.0, 7.0, 2.0, 9.0, 2.0))
    rect = (restored.get("geometry") or {}).get("rect") or {}
    assert rect.get("x") == pytest.approx(7.0)
    assert rect.get("y") == pytest.approx(1.0)
    assert rect.get("width") == pytest.approx(2.0)
    assert rect.get("height") == pytest.approx(1.0)


def test_inverse_aug_box_flips_qbox_vflip_and_rebuilds_rect() -> None:
    service = _build_service()
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": (1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0),
        "geometry": {"rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 1.0}},
    }
    restored = service._inverse_aug_box(name="vflip", row=row, width=10, height=8)
    assert restored["qbox"] == pytest.approx((1.0, 7.0, 3.0, 7.0, 3.0, 6.0, 1.0, 6.0))
    rect = (restored.get("geometry") or {}).get("rect") or {}
    assert rect.get("x") == pytest.approx(1.0)
    assert rect.get("y") == pytest.approx(6.0)
    assert rect.get("width") == pytest.approx(2.0)
    assert rect.get("height") == pytest.approx(1.0)


def test_inverse_aug_box_restores_rot90_qbox_and_rect() -> None:
    service = _build_service()
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": (1.0, 9.0, 1.0, 7.0, 2.0, 7.0, 2.0, 9.0),
        "geometry": {"rect": {"x": 1.0, "y": 7.0, "width": 1.0, "height": 2.0}},
    }
    restored = service._inverse_aug_box(name="rot90", row=row, width=10, height=8)
    assert restored["qbox"] == pytest.approx((1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0), abs=1e-6)
    rect = (restored.get("geometry") or {}).get("rect") or {}
    assert rect.get("x") == pytest.approx(1.0, abs=1e-6)
    assert rect.get("y") == pytest.approx(1.0, abs=1e-6)
    assert rect.get("width") == pytest.approx(2.0, abs=1e-6)
    assert rect.get("height") == pytest.approx(1.0, abs=1e-6)


def test_inverse_aug_box_restores_affine_qbox_and_rect() -> None:
    service = _build_service()
    original = (4.0, 3.0, 6.0, 3.0, 6.0, 5.0, 4.0, 5.0)
    aug = _rotate_quad8(original, angle_deg=12.0, cx=5.0, cy=4.0)
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": aug,
        "geometry": {"rect": {"x": min(aug[0::2]), "y": min(aug[1::2]), "width": max(aug[0::2]) - min(aug[0::2]), "height": max(aug[1::2]) - min(aug[1::2])}},
    }
    restored = service._inverse_aug_box(name="affine_rot_p12", row=row, width=10, height=8)
    assert restored["qbox"] == pytest.approx(original, abs=1e-6)
    rect = (restored.get("geometry") or {}).get("rect") or {}
    assert rect.get("x") == pytest.approx(4.0, abs=1e-6)
    assert rect.get("y") == pytest.approx(3.0, abs=1e-6)
    assert rect.get("width") == pytest.approx(2.0, abs=1e-6)
    assert rect.get("height") == pytest.approx(2.0, abs=1e-6)


def _rotate_quad8(quad8: tuple[float, ...], *, angle_deg: float, cx: float, cy: float) -> tuple[float, ...]:
    out: list[float] = []
    for i in range(0, 8, 2):
        x, y = _rotate_point(quad8[i], quad8[i + 1], angle_deg=angle_deg, cx=cx, cy=cy)
        out.extend([x, y])
    return tuple(out)


def _rotate_point(x: float, y: float, *, angle_deg: float, cx: float, cy: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    cos_t = math.cos(rad)
    sin_t = math.sin(rad)
    dx = x - cx
    dy = y - cy
    return (
        dx * cos_t - dy * sin_t + cx,
        dx * sin_t + dy * cos_t + cy,
    )
