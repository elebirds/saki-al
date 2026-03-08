from __future__ import annotations

import math

import pytest

from saki_plugin_sdk.strategies import aug_iou
from saki_plugin_sdk.strategies.aug_iou import DetectionBox, box_iou, build_detection_boxes


def test_qbox_iou_uses_polygon_when_shapely_available() -> None:
    if aug_iou.Polygon is None:
        pytest.skip("shapely is not installed")

    square = DetectionBox(
        class_index=0,
        confidence=0.9,
        bounds=(-1.0, -1.0, 1.0, 1.0),
        qbox=(-1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0),
    )
    diamond = DetectionBox(
        class_index=0,
        confidence=0.9,
        bounds=(-1.0, -1.0, 1.0, 1.0),
        qbox=(0.0, -1.0, 1.0, 0.0, 0.0, 1.0, -1.0, 0.0),
    )

    iou = box_iou(square, diamond)
    assert iou < 1.0
    assert math.isclose(iou, 0.5, rel_tol=1e-6, abs_tol=1e-6)


def test_build_detection_boxes_supports_geometry_obb() -> None:
    rows = [
        {
            "class_index": 2,
            "confidence": 0.7,
            "geometry": {
                "obb": {
                    "cx": 10.0,
                    "cy": 20.0,
                    "width": 8.0,
                    "height": 4.0,
                    "angle_deg_ccw": 30.0,
                }
            },
        }
    ]
    boxes = build_detection_boxes(rows)
    assert len(boxes) == 1
    box = boxes[0]
    assert box.qbox is not None
    assert box.bounds[2] > box.bounds[0]
    assert box.bounds[3] > box.bounds[1]


def test_build_detection_boxes_keeps_rect_compatibility() -> None:
    rows = [
        {
            "class_index": 1,
            "confidence": 0.8,
            "geometry": {"rect": {"x": 3.0, "y": 4.0, "width": 5.0, "height": 6.0}},
        }
    ]
    boxes = build_detection_boxes(rows)
    assert len(boxes) == 1
    box = boxes[0]
    assert box.qbox is None
    assert box.bounds == (3.0, 4.0, 8.0, 10.0)


def test_qbox_iou_falls_back_to_aabb_when_shapely_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aug_iou, "Polygon", None)
    square = DetectionBox(
        class_index=0,
        confidence=0.9,
        bounds=(-1.0, -1.0, 1.0, 1.0),
        qbox=(-1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0),
    )
    diamond = DetectionBox(
        class_index=0,
        confidence=0.9,
        bounds=(-1.0, -1.0, 1.0, 1.0),
        qbox=(0.0, -1.0, 1.0, 0.0, 0.0, 1.0, -1.0, 0.0),
    )
    iou = box_iou(square, diamond)
    assert math.isclose(iou, 1.0, rel_tol=1e-6, abs_tol=1e-6)
