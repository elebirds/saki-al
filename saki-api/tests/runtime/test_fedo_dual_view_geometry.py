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
