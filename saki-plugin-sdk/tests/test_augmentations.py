from __future__ import annotations

import math
import random
from typing import Any

import pytest

from saki_plugin_sdk.augmentations import (
    AugmentationSpec,
    build_augmented_views,
    build_default_augmentation_specs,
    inverse_augmented_prediction_row,
)

_DEFAULT_ORDER = [
    "identity",
    "hflip",
    "vflip",
    "rot90",
    "rot180",
    "rot270",
    "transpose",
    "transverse",
    "bright",
    "dark",
    "contrast_up",
    "affine_rot_p12",
    "affine_rot_m12",
]

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from PIL import Image

_D4_OPS = ("identity", "hflip", "vflip", "rot90", "rot180", "rot270", "transpose", "transverse")
_AFFINE_OPS = ("affine_rot_p12", "affine_rot_m12")
_PIXEL_OPS = ("bright", "dark", "contrast_up")


def test_build_default_augmentation_specs_has_fixed_order() -> None:
    specs = build_default_augmentation_specs()
    assert [item.name for item in specs] == _DEFAULT_ORDER


def test_build_augmented_views_has_expected_shapes_and_extra_dedupe() -> None:
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    views = build_augmented_views(
        image,
        np_mod=np,
        image_cls=Image,
        extra_specs=[
            AugmentationSpec(name="bright", apply=lambda arr, np_mod, _img: np_mod.zeros_like(arr)),
            AugmentationSpec(name="custom_keep", apply=lambda arr, _np, _img: arr),
        ],
    )
    names = [view.name for view in views]
    assert names[: len(_DEFAULT_ORDER)] == _DEFAULT_ORDER
    assert names.count("bright") == 1
    assert names[-1] == "custom_keep"

    shape_map = {view.name: tuple(view.image.shape[:2]) for view in views}
    assert shape_map["identity"] == (8, 10)
    assert shape_map["rot90"] == (10, 8)
    assert shape_map["rot270"] == (10, 8)
    assert shape_map["transpose"] == (10, 8)
    assert shape_map["transverse"] == (10, 8)
    assert shape_map["affine_rot_p12"] == (8, 10)


@pytest.mark.parametrize(
    "op_name",
    ["identity", "hflip", "vflip", "rot90", "rot180", "rot270", "transpose", "transverse"],
)
def test_inverse_augmented_prediction_row_restores_qbox_for_d4(op_name: str) -> None:
    w, h = 12.0, 8.0
    qbox = (2.0, 1.0, 6.0, 1.0, 6.0, 3.0, 2.0, 3.0)
    qbox_aug = _forward_quad8(op_name, qbox, width=w, height=h)
    view = _find_view(op_name, width=int(w), height=int(h))
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.9,
        "qbox": qbox_aug,
        "geometry": {"rect": _rect_from_quad8(qbox_aug)},
    }

    restored = inverse_augmented_prediction_row(row, view=view)
    assert restored["qbox"] == pytest.approx(qbox, abs=1e-6)
    assert (restored["geometry"] or {}).get("rect") == pytest.approx(_rect_from_quad8(qbox), abs=1e-6)


@pytest.mark.parametrize("op_name", ["affine_rot_p12", "affine_rot_m12"])
def test_inverse_augmented_prediction_row_restores_qbox_for_affine(op_name: str) -> None:
    w, h = 100.0, 80.0
    qbox = (40.0, 30.0, 60.0, 30.0, 60.0, 50.0, 40.0, 50.0)
    qbox_aug = _forward_quad8(op_name, qbox, width=w, height=h)
    view = _find_view(op_name, width=int(w), height=int(h))
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.9,
        "qbox": qbox_aug,
        "geometry": {"rect": _rect_from_quad8(qbox_aug)},
    }

    restored = inverse_augmented_prediction_row(row, view=view)
    assert restored["qbox"] == pytest.approx(qbox, abs=1e-6)
    assert (restored["geometry"] or {}).get("rect") == pytest.approx(_rect_from_quad8(qbox), abs=1e-6)


def test_inverse_augmented_prediction_row_geometry_rect_path() -> None:
    w, h = 12.0, 8.0
    op_name = "rot90"
    qbox = (2.0, 1.0, 6.0, 1.0, 6.0, 3.0, 2.0, 3.0)
    qbox_aug = _forward_quad8(op_name, qbox, width=w, height=h)
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "geometry": {"rect": _rect_from_quad8(qbox_aug)},
    }
    view = _find_view(op_name, width=int(w), height=int(h))
    restored = inverse_augmented_prediction_row(row, view=view)
    assert "qbox" not in restored
    assert (restored["geometry"] or {}).get("rect") == pytest.approx(_rect_from_quad8(qbox), abs=1e-6)


def test_inverse_augmented_prediction_row_geometry_to_quad8_path() -> None:
    row = {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.8,
        "geometry": {
            "obb": {
                "cx": 5.0,
                "cy": 4.0,
                "width": 4.0,
                "height": 2.0,
                "angle_deg_ccw": 0.0,
            }
        },
    }
    view = _find_view("identity", width=10, height=8)
    restored = inverse_augmented_prediction_row(row, view=view)
    assert "qbox" not in restored
    assert (restored["geometry"] or {}).get("rect") == pytest.approx(
        {"x": 3.0, "y": 3.0, "width": 4.0, "height": 2.0},
        abs=1e-6,
    )


def test_inverse_augmented_prediction_row_invalid_payload_falls_back_to_zero_rect() -> None:
    row = {
        "class_index": "x",
        "class_name": None,
        "confidence": "bad",
        "geometry": {"unknown": {}},
    }
    view = _find_view("identity", width=10, height=8)
    restored = inverse_augmented_prediction_row(row, view=view)
    assert restored["class_index"] == 0
    assert restored["class_name"] == ""
    assert restored["confidence"] == 0.0
    assert (restored["geometry"] or {}).get("rect") == pytest.approx(
        {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
        abs=1e-6,
    )


def test_inverse_augmented_prediction_row_pixel_ops_keep_geometry_many_samples() -> None:
    width, height = 320, 240
    view_map = _build_view_map(width=width, height=height)
    rng = random.Random(20260308)
    for op_name in _PIXEL_OPS:
        view = view_map[op_name]
        for _ in range(200):
            qbox = _random_quad8(rng, width=float(width), height=float(height), border=0.0)
            row = {
                "class_index": 0,
                "class_name": "obj",
                "confidence": 0.7,
                "qbox": qbox,
                "geometry": {"rect": _rect_from_quad8(qbox)},
            }
            restored = inverse_augmented_prediction_row(row, view=view)
            assert restored["qbox"] == pytest.approx(qbox, abs=1e-6)
            assert (restored["geometry"] or {}).get("rect") == pytest.approx(_rect_from_quad8(qbox), abs=1e-6)


def test_inverse_augmented_prediction_row_d4_randomized_roundtrip_many_samples() -> None:
    width, height = 320, 240
    view_map = _build_view_map(width=width, height=height)
    rng = random.Random(20260309)
    for op_name in _D4_OPS:
        view = view_map[op_name]
        for _ in range(220):
            qbox = _random_quad8(rng, width=float(width), height=float(height), border=0.0)
            qbox_aug = _forward_quad8(op_name, qbox, width=float(width), height=float(height))
            row = {
                "class_index": 1,
                "class_name": "obj",
                "confidence": 0.9,
                "qbox": qbox_aug,
                "geometry": {"rect": _rect_from_quad8(qbox_aug)},
            }
            restored = inverse_augmented_prediction_row(row, view=view)
            assert restored["qbox"] == pytest.approx(qbox, abs=1e-6)
            assert (restored["geometry"] or {}).get("rect") == pytest.approx(_rect_from_quad8(qbox), abs=1e-6)


def test_inverse_augmented_prediction_row_affine_randomized_roundtrip_many_samples() -> None:
    width, height = 320, 240
    view_map = _build_view_map(width=width, height=height)
    rng = random.Random(20260310)
    for op_name in _AFFINE_OPS:
        view = view_map[op_name]
        for _ in range(220):
            qbox = _random_quad8(rng, width=float(width), height=float(height), border=6.0)
            qbox_aug = _forward_quad8(op_name, qbox, width=float(width), height=float(height))
            row = {
                "class_index": 1,
                "class_name": "obj",
                "confidence": 0.9,
                "qbox": qbox_aug,
                "geometry": {"rect": _rect_from_quad8(qbox_aug)},
            }
            restored = inverse_augmented_prediction_row(row, view=view)
            assert restored["qbox"] == pytest.approx(qbox, abs=1e-6)
            assert (restored["geometry"] or {}).get("rect") == pytest.approx(_rect_from_quad8(qbox), abs=1e-6)


def test_inverse_augmented_prediction_row_identity_clamps_out_of_bound_points() -> None:
    view = _find_view("identity", width=100, height=80)
    row = {
        "class_index": 1,
        "class_name": "obj",
        "confidence": 1.2,
        "qbox": (-3.0, -1.0, 105.0, -2.0, 120.0, 90.0, -7.0, 95.0),
        "geometry": {"rect": {"x": -3.0, "y": -1.0, "width": 127.0, "height": 96.0}},
    }
    restored = inverse_augmented_prediction_row(row, view=view)
    qbox = restored["qbox"]
    assert all(0.0 <= qbox[i] <= 100.0 for i in (0, 2, 4, 6))
    assert all(0.0 <= qbox[i] <= 80.0 for i in (1, 3, 5, 7))
    assert restored["confidence"] == 1.0


def test_custom_spec_inverse_point_is_used() -> None:
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    custom = AugmentationSpec(
        name="shift_x_plus_3",
        apply=lambda arr, _np_mod, _img: arr,
        inverse_point=lambda x, y, _view: (x - 3.0, y),
    )
    views = build_augmented_views(image, np_mod=np, image_cls=Image, extra_specs=[custom])
    view = next(item for item in views if item.name == "shift_x_plus_3")
    qbox_aug = (6.0, 1.0, 8.0, 1.0, 8.0, 3.0, 6.0, 3.0)
    row = {
        "class_index": 1,
        "class_name": "obj",
        "confidence": 0.5,
        "qbox": qbox_aug,
        "geometry": {"rect": _rect_from_quad8(qbox_aug)},
    }
    restored = inverse_augmented_prediction_row(row, view=view)
    assert restored["qbox"] == pytest.approx((3.0, 1.0, 5.0, 1.0, 5.0, 3.0, 3.0, 3.0), abs=1e-6)


def _find_view(name: str, *, width: int, height: int):
    view_map = _build_view_map(width=width, height=height)
    item = view_map.get(name)
    if item is not None:
        return item
    raise AssertionError(f"view not found: {name}")


def _build_view_map(*, width: int, height: int) -> dict[str, Any]:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    views = build_augmented_views(image, np_mod=np, image_cls=Image)
    return {item.name: item for item in views}


def _forward_quad8(op_name: str, quad8: tuple[float, ...], *, width: float, height: float) -> tuple[float, ...]:
    out: list[float] = []
    for i in range(0, 8, 2):
        x, y = _forward_point(op_name, quad8[i], quad8[i + 1], width=width, height=height)
        out.extend([x, y])
    return tuple(out)


def _forward_point(op_name: str, x: float, y: float, *, width: float, height: float) -> tuple[float, float]:
    if op_name == "identity":
        return x, y
    if op_name == "hflip":
        return width - x, y
    if op_name == "vflip":
        return x, height - y
    if op_name == "rot90":
        return y, width - x
    if op_name == "rot180":
        return width - x, height - y
    if op_name == "rot270":
        return height - y, x
    if op_name == "transpose":
        return y, x
    if op_name == "transverse":
        return height - y, width - x
    if op_name == "affine_rot_p12":
        return _rotate_point(x, y, angle_deg=12.0, cx=width / 2.0, cy=height / 2.0)
    if op_name == "affine_rot_m12":
        return _rotate_point(x, y, angle_deg=-12.0, cx=width / 2.0, cy=height / 2.0)
    raise AssertionError(f"unsupported op: {op_name}")


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


def _rect_from_quad8(quad8: tuple[float, ...]) -> dict[str, float]:
    xs = [quad8[0], quad8[2], quad8[4], quad8[6]]
    ys = [quad8[1], quad8[3], quad8[5], quad8[7]]
    x0 = min(xs)
    y0 = min(ys)
    x1 = max(xs)
    y1 = max(ys)
    return {
        "x": float(x0),
        "y": float(y0),
        "width": float(max(0.0, x1 - x0)),
        "height": float(max(0.0, y1 - y0)),
    }


def _random_quad8(
    rng: random.Random,
    *,
    width: float,
    height: float,
    border: float,
) -> tuple[float, ...]:
    min_x = max(0.0, float(border))
    max_x = max(min_x + 1e-3, float(width) - float(border))
    min_y = max(0.0, float(border))
    max_y = max(min_y + 1e-3, float(height) - float(border))
    out: list[float] = []
    for _ in range(4):
        out.append(rng.uniform(min_x, max_x))
        out.append(rng.uniform(min_y, max_y))
    return tuple(out)
