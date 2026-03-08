from __future__ import annotations

import pytest

from saki_ir import (
    flip_quad8,
    geometry_to_quad8_local,
    normalize_quad8,
    quad8_to_aabb_rect,
    quad8_to_obb_payload,
)
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def test_normalize_quad8_accepts_nested_values() -> None:
    value = [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]]
    assert normalize_quad8(value) == (0.0, 0.0, 2.0, 0.0, 2.0, 1.0, 0.0, 1.0)


def test_geometry_to_quad8_local_supports_proto_and_payload() -> None:
    proto = ir.Geometry(obb=ir.ObbGeometry(cx=10.0, cy=10.0, width=4.0, height=2.0, angle_deg_ccw=0.0))
    quad_from_proto = geometry_to_quad8_local(proto)
    quad_from_payload = geometry_to_quad8_local(
        {
            "obb": {
                "cx": 10.0,
                "cy": 10.0,
                "width": 4.0,
                "height": 2.0,
                "angleDegCcw": 0.0,
            }
        }
    )
    assert quad_from_proto == pytest.approx(quad_from_payload)


def test_quad8_to_aabb_rect_and_flip() -> None:
    quad = (1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0)
    assert quad8_to_aabb_rect(quad) == pytest.approx((1.0, 1.0, 2.0, 1.0))
    assert flip_quad8(quad, op="hflip", width=10, height=8) == pytest.approx((9.0, 1.0, 7.0, 1.0, 7.0, 2.0, 9.0, 2.0))
    assert flip_quad8(quad, op="vflip", width=10, height=8) == pytest.approx((1.0, 7.0, 3.0, 7.0, 3.0, 6.0, 1.0, 6.0))


def test_quad8_to_obb_payload_strict() -> None:
    quad = (0.0, 0.0, 4.0, 0.0, 4.0, 2.0, 0.0, 2.0)
    payload = quad8_to_obb_payload(quad, fit_mode="strict")
    obb = payload["obb"]
    assert obb["cx"] == pytest.approx(2.0, abs=1e-6)
    assert obb["cy"] == pytest.approx(1.0, abs=1e-6)
    assert obb["width"] == pytest.approx(4.0, abs=1e-6)
    assert obb["height"] == pytest.approx(2.0, abs=1e-6)
    assert obb["angle_deg_ccw"] == pytest.approx(0.0, abs=1e-6)


def test_quad8_to_obb_payload_strict_then_min_area_fallback() -> None:
    # 非严格矩形（平行四边形），strict 会失败，fallback 会给出最小外接矩形。
    quad = (0.0, 0.0, 4.0, 0.0, 5.0, 2.0, 1.0, 2.0)
    with pytest.raises(ValueError):
        quad8_to_obb_payload(quad, fit_mode="strict")
    payload = quad8_to_obb_payload(quad, fit_mode="strict_then_min_area")
    obb = payload["obb"]
    assert obb["width"] > 0.0
    assert obb["height"] > 0.0
