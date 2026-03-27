from __future__ import annotations

import math
import threading
from pathlib import Path

import pytest

from saki_ir import quad8_to_obb_payload
from saki_plugin_yolo_det import predict_service as predict_service_module
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


def _assert_geometry_matches_qbox(row: dict[str, object], expected_qbox: tuple[float, ...]) -> None:
    geometry = dict((row.get("geometry") if isinstance(row, dict) else {}) or {})
    expected = quad8_to_obb_payload(expected_qbox, fit_mode="strict_then_min_area")
    actual_obb = dict(geometry.get("obb") or {})
    expected_obb = dict(expected.get("obb") or {})
    assert actual_obb.get("cx") == pytest.approx(expected_obb.get("cx"))
    assert actual_obb.get("cy") == pytest.approx(expected_obb.get("cy"))
    assert actual_obb.get("width") == pytest.approx(expected_obb.get("width"))
    assert actual_obb.get("height") == pytest.approx(expected_obb.get("height"))
    assert actual_obb.get("angle_deg_ccw") == pytest.approx(expected_obb.get("angle_deg_ccw"))


def test_extract_predictions_obb_includes_qbox_and_obb_geometry() -> None:
    service = _build_service()
    rows = service._extract_predictions(_ObbResult())
    assert len(rows) == 1
    row = rows[0]
    assert row["class_index"] == 1
    assert row["class_name"] == "car"
    assert row["confidence"] == pytest.approx(0.9)
    assert row["qbox"] == pytest.approx((1.0, 2.0, 5.0, 2.0, 5.0, 4.0, 1.0, 4.0))
    _assert_geometry_matches_qbox(row, (1.0, 2.0, 5.0, 2.0, 5.0, 4.0, 1.0, 4.0))


def test_inverse_aug_box_flips_qbox_hflip_and_rebuilds_obb() -> None:
    service = _build_service()
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": (1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0),
        "geometry": {"rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 1.0}},
    }
    restored = service._inverse_aug_box(name="hflip", row=row, width=10, height=8)
    expected_qbox = (9.0, 1.0, 7.0, 1.0, 7.0, 2.0, 9.0, 2.0)
    assert restored["qbox"] == pytest.approx(expected_qbox)
    _assert_geometry_matches_qbox(restored, expected_qbox)


def test_inverse_aug_box_flips_qbox_vflip_and_rebuilds_obb() -> None:
    service = _build_service()
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": (1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0),
        "geometry": {"rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 1.0}},
    }
    restored = service._inverse_aug_box(name="vflip", row=row, width=10, height=8)
    expected_qbox = (1.0, 7.0, 3.0, 7.0, 3.0, 6.0, 1.0, 6.0)
    assert restored["qbox"] == pytest.approx(expected_qbox)
    _assert_geometry_matches_qbox(restored, expected_qbox)


def test_inverse_aug_box_restores_rot90_qbox_and_obb() -> None:
    service = _build_service()
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "qbox": (1.0, 9.0, 1.0, 7.0, 2.0, 7.0, 2.0, 9.0),
        "geometry": {"rect": {"x": 1.0, "y": 7.0, "width": 1.0, "height": 2.0}},
    }
    restored = service._inverse_aug_box(name="rot90", row=row, width=10, height=8)
    expected_qbox = (1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0)
    assert restored["qbox"] == pytest.approx(expected_qbox, abs=1e-6)
    _assert_geometry_matches_qbox(restored, expected_qbox)


def test_inverse_aug_box_restores_affine_qbox_and_obb() -> None:
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
    _assert_geometry_matches_qbox(restored, original)


def test_score_unlabeled_sync_aug_iou_uses_bounded_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"\x00")
    service = _build_service()
    monkeypatch.setattr(service, "_get_or_load_model", lambda **_kwargs: object())
    captured: dict[str, object] = {}

    def _pipeline(**kwargs):
        captured["predict_batch_size"] = kwargs.get("predict_batch_size")
        captured["sample_batch_size"] = kwargs.get("sample_batch_size")
        captured["pipeline_workers"] = kwargs.get("pipeline_workers")
        captured["enabled_aug_names"] = kwargs.get("enabled_aug_names")
        return [
            {
                "sample_id": "sample-a",
                "score": 0.7,
                "reason": {"score": 0.7},
                "prediction_snapshot": {
                    "strategy": "aug_iou_disagreement",
                    "aug_count": 2,
                    "pred_per_aug": [1, 1],
                    "base_predictions": [],
                },
            }
        ]

    monkeypatch.setattr(
        predict_service_module,
        "score_augmented_samples_with_pipeline",
        _pipeline,
    )

    rows = service._score_unlabeled_sync(
        model_path="/tmp/fake.pt",
        unlabeled_samples=[{"id": "sample-a", "local_path": str(image_path)}],
        strategy="aug_iou_disagreement",
        conf=0.25,
        imgsz=1024,
        batch=16,
        device="cuda:0",
        random_seed=7,
        round_index=1,
        aug_enabled_names=("identity", "rot90"),
        aug_iou_mode="obb",
        aug_iou_boundary_d=3,
        aug_iou_sample_batch_size=2,
        aug_iou_pipeline_workers=3,
    )

    assert len(rows) == 1
    assert captured["predict_batch_size"] == 16
    assert captured["sample_batch_size"] == 2
    assert captured["pipeline_workers"] == 3
    assert captured["enabled_aug_names"] == ("identity", "rot90")


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
