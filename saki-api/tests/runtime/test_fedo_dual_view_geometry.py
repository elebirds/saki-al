from __future__ import annotations

import numpy as np
import pytest

from saki_api.modules.annotation.extensions.sync.handlers.dual_view import DualViewSyncHandler


def _edge_angle_deg(p0: np.ndarray, p1: np.ndarray) -> float:
    vec = p1 - p0
    return float(np.degrees(np.arctan2(vec[1], vec[0])))


def test_geometry_to_vertices_obb_respects_ccw_angle_snake_case() -> None:
    geometry = {
        "obb": {
            "cx": 100.0,
            "cy": 50.0,
            "width": 20.0,
            "height": 10.0,
            "angle_deg_ccw": 30.0,
        }
    }
    points = DualViewSyncHandler._geometry_to_vertices(geometry)
    angle = _edge_angle_deg(points[0], points[1])
    assert angle == pytest.approx(30.0, abs=1e-3)


def test_geometry_to_vertices_obb_accepts_camel_case_angle_key() -> None:
    geometry = {
        "obb": {
            "cx": 100.0,
            "cy": 50.0,
            "width": 20.0,
            "height": 10.0,
            "angleDegCcw": 30.0,
        }
    }
    points = DualViewSyncHandler._geometry_to_vertices(geometry)
    angle = _edge_angle_deg(points[0], points[1])
    assert angle == pytest.approx(30.0, abs=1e-3)


def test_resolve_source_view_rejects_legacy_l_wd_value() -> None:
    with pytest.raises(ValueError):
        DualViewSyncHandler._resolve_source_view({"view": "L-wd"})


def test_obb_vertices_to_geometry_returns_normalized_obb() -> None:
    vertices = np.asarray(
        [
            [90.0, 45.0],
            [110.0, 45.0],
            [110.0, 55.0],
            [90.0, 55.0],
        ],
        dtype=np.float32,
    )
    geometry = DualViewSyncHandler._obb_vertices_to_geometry(vertices)
    obb = geometry.get("obb") if isinstance(geometry, dict) else None
    assert isinstance(obb, dict)
    assert float(obb.get("width", 0.0)) > 0.0
    assert float(obb.get("height", 0.0)) > 0.0
