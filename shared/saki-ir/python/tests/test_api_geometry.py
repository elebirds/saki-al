from __future__ import annotations

import pytest

from saki_ir import (
    IRValidationError,
    infer_shape,
    normalize_geometry_payload,
    parse_geometry,
    validate_geometry_payload,
)


def test_rect_geometry_normalize_success() -> None:
    payload = {
        "rect": {
            "x": 10,
            "y": 12,
            "width": 20,
            "height": 30,
        }
    }
    normalized = normalize_geometry_payload(payload)
    assert "rect" in normalized
    assert normalized["rect"]["width"] == pytest.approx(20.0)
    assert normalized["rect"]["height"] == pytest.approx(30.0)
    assert infer_shape(normalized) == "rect"


def test_obb_geometry_parse_success() -> None:
    payload = {
        "obb": {
            "cx": 100,
            "cy": 50,
            "width": 10,
            "height": 20,
            "angle_deg_ccw": 30,
        }
    }
    geometry = parse_geometry(payload)
    assert geometry.WhichOneof("shape") == "obb"
    validate_geometry_payload(payload)


def test_geometry_invalid_negative_size_returns_structured_path() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_geometry_payload(
            {
                "rect": {
                    "x": 0,
                    "y": 0,
                    "width": -1,
                    "height": 10,
                }
            }
        )
    exc = exc_info.value
    first = exc.issues[0]
    assert first.code == "IR_GEOMETRY_INVALID"
    assert first.path == "geometry"


def test_geometry_missing_shape_fails() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        parse_geometry({})
    first = exc_info.value.issues[0]
    assert first.code == "IR_GEOMETRY_INVALID"
    assert first.path == "geometry.shape"
