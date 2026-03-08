from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from saki_ir import geometry_to_quad8_local, normalize_quad8, quad8_to_aabb_rect

InversePointFn = Callable[[float, float, "AugmentedView"], tuple[float, float]]
ApplyImageFn = Callable[[Any, Any, Any], Any]

_DEFAULT_AUGMENTATION_ORDER: tuple[str, ...] = (
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
)

_PIXEL_ONLY_OPS: set[str] = {"identity", "bright", "dark", "contrast_up"}
_D4_OPS: set[str] = {
    "hflip",
    "vflip",
    "rot90",
    "rot180",
    "rot270",
    "transpose",
    "transverse",
}
_AFFINE_OP_ANGLE_DEG: dict[str, float] = {
    "affine_rot_p12": 12.0,
    "affine_rot_m12": -12.0,
}


@dataclass(frozen=True)
class AugmentationSpec:
    name: str
    apply: ApplyImageFn | None = None
    inverse_point: InversePointFn | None = None


@dataclass(frozen=True)
class AugmentedView:
    name: str
    image: Any
    orig_width: int
    orig_height: int
    width: int
    height: int
    spec: AugmentationSpec
    inverse_point: InversePointFn


def build_default_augmentation_specs() -> list[AugmentationSpec]:
    return [AugmentationSpec(name=name) for name in _DEFAULT_AUGMENTATION_ORDER]


def build_augmented_views(
    image: Any,
    *,
    np_mod: Any,
    image_cls: Any,
    extra_specs: tuple[AugmentationSpec, ...] | list[AugmentationSpec] = (),
) -> list[AugmentedView]:
    base = np_mod.ascontiguousarray(image)
    if getattr(base, "ndim", 0) < 2:
        raise ValueError("image must be at least 2D (H, W[, C])")

    orig_h = int(base.shape[0])
    orig_w = int(base.shape[1])
    specs = _merge_specs(extra_specs=extra_specs)

    views: list[AugmentedView] = []
    for raw_spec in specs:
        spec = _normalize_spec(raw_spec)
        aug = _apply_spec(spec=spec, image=base, np_mod=np_mod, image_cls=image_cls)
        aug_arr = np_mod.ascontiguousarray(aug)
        if getattr(aug_arr, "ndim", 0) < 2:
            raise ValueError(f"augmentation '{spec.name}' must return at least 2D image")
        aug_h = int(aug_arr.shape[0])
        aug_w = int(aug_arr.shape[1])
        views.append(
            AugmentedView(
                name=spec.name,
                image=aug_arr,
                orig_width=orig_w,
                orig_height=orig_h,
                width=aug_w,
                height=aug_h,
                spec=spec,
                inverse_point=_resolve_inverse_point(spec),
            )
        )
    return views


def inverse_augmented_prediction_row(
    row: dict[str, Any],
    *,
    view: AugmentedView,
) -> dict[str, Any]:
    source = dict(row or {})
    out: dict[str, Any] = dict(source)
    out["class_index"] = _to_int(source.get("class_index", 0), 0)
    out["class_name"] = str(source.get("class_name") or "")
    out["confidence"] = _to_unit_float(source.get("confidence", 0.0), 0.0)

    has_explicit_qbox = normalize_quad8(source.get("qbox")) is not None
    qbox = normalize_quad8(source.get("qbox"))
    if qbox is None:
        geometry = source.get("geometry")
        if geometry is not None:
            try:
                qbox = geometry_to_quad8_local(geometry)
            except Exception:
                qbox = None

    if qbox is not None:
        qbox_inv = _inverse_quad8_to_original(qbox, view=view)
        x, y, w, h = quad8_to_aabb_rect(qbox_inv)
        out["geometry"] = {
            "rect": {
                "x": x,
                "y": y,
                "width": w,
                "height": h,
            }
        }
        if has_explicit_qbox:
            out["qbox"] = qbox_inv
        else:
            out.pop("qbox", None)
        return out

    rect = {}
    geometry = source.get("geometry")
    if isinstance(geometry, dict):
        maybe_rect = geometry.get("rect")
        if isinstance(maybe_rect, dict):
            rect = maybe_rect
    x = _to_float(rect.get("x", 0.0), 0.0)
    y = _to_float(rect.get("y", 0.0), 0.0)
    w = max(0.0, _to_float(rect.get("width", 0.0), 0.0))
    h = max(0.0, _to_float(rect.get("height", 0.0), 0.0))
    qbox_rect = (
        x,
        y,
        x + w,
        y,
        x + w,
        y + h,
        x,
        y + h,
    )
    qbox_inv = _inverse_quad8_to_original(qbox_rect, view=view)
    x2, y2, w2, h2 = quad8_to_aabb_rect(qbox_inv)
    out.pop("qbox", None)
    out["geometry"] = {
        "rect": {
            "x": x2,
            "y": y2,
            "width": w2,
            "height": h2,
        }
    }
    return out


def _normalize_spec(spec: AugmentationSpec) -> AugmentationSpec:
    name = _normalize_name(spec.name)
    return AugmentationSpec(name=name, apply=spec.apply, inverse_point=spec.inverse_point)


def _merge_specs(
    *,
    extra_specs: tuple[AugmentationSpec, ...] | list[AugmentationSpec],
) -> list[AugmentationSpec]:
    merged: list[AugmentationSpec] = []
    seen: set[str] = set()

    for spec in build_default_augmentation_specs():
        normalized = _normalize_spec(spec)
        if normalized.name in seen:
            continue
        seen.add(normalized.name)
        merged.append(normalized)

    for raw in extra_specs:
        normalized = _normalize_spec(raw)
        if normalized.name in seen:
            continue
        seen.add(normalized.name)
        merged.append(normalized)

    return merged


def _normalize_name(value: Any) -> str:
    name = str(value or "").strip().lower()
    if not name:
        raise ValueError("augmentation name cannot be empty")
    return name


def _apply_spec(
    *,
    spec: AugmentationSpec,
    image: Any,
    np_mod: Any,
    image_cls: Any,
) -> Any:
    name = spec.name
    if name in _DEFAULT_AUGMENTATION_ORDER:
        return _apply_builtin(name=name, image=image, np_mod=np_mod, image_cls=image_cls)
    if spec.apply is not None:
        return spec.apply(image, np_mod, image_cls)
    return image


def _apply_builtin(
    *,
    name: str,
    image: Any,
    np_mod: Any,
    image_cls: Any,
) -> Any:
    if name == "identity":
        return image
    if name == "hflip":
        return np_mod.ascontiguousarray(image[:, ::-1, ...])
    if name == "vflip":
        return np_mod.ascontiguousarray(image[::-1, :, ...])
    if name == "rot90":
        return np_mod.ascontiguousarray(np_mod.rot90(image, k=1, axes=(0, 1)))
    if name == "rot180":
        return np_mod.ascontiguousarray(np_mod.rot90(image, k=2, axes=(0, 1)))
    if name == "rot270":
        return np_mod.ascontiguousarray(np_mod.rot90(image, k=3, axes=(0, 1)))
    if name == "transpose":
        axes = (1, 0, *range(2, int(image.ndim)))
        return np_mod.ascontiguousarray(np_mod.transpose(image, axes))
    if name == "transverse":
        axes = (1, 0, *range(2, int(image.ndim)))
        return np_mod.ascontiguousarray(np_mod.transpose(image[::-1, ::-1, ...], axes))
    if name == "bright":
        return np_mod.clip(image.astype(np_mod.float32) * 1.2, 0, 255).astype(np_mod.uint8)
    if name == "dark":
        return np_mod.clip(image.astype(np_mod.float32) * 0.8, 0, 255).astype(np_mod.uint8)
    if name == "contrast_up":
        centered = image.astype(np_mod.float32) - 127.5
        return np_mod.clip(centered * 1.2 + 127.5, 0, 255).astype(np_mod.uint8)
    if name in _AFFINE_OP_ANGLE_DEG:
        return _apply_affine_rotate(
            image=image,
            angle_deg=_AFFINE_OP_ANGLE_DEG[name],
            np_mod=np_mod,
            image_cls=image_cls,
        )
    raise ValueError(f"unsupported augmentation name: {name}")


def _apply_affine_rotate(
    *,
    image: Any,
    angle_deg: float,
    np_mod: Any,
    image_cls: Any,
) -> Any:
    pil_image = image_cls.fromarray(_ensure_uint8(image=image, np_mod=np_mod))
    resampling = getattr(image_cls, "Resampling", image_cls)
    bilinear = getattr(resampling, "BILINEAR", getattr(image_cls, "BILINEAR"))
    out = pil_image.rotate(
        angle=float(angle_deg),
        resample=bilinear,
        expand=False,
        fillcolor=(114, 114, 114),
    )
    return np_mod.ascontiguousarray(np_mod.array(out))


def _ensure_uint8(*, image: Any, np_mod: Any) -> Any:
    if getattr(image, "dtype", None) == np_mod.uint8:
        return image
    return np_mod.clip(np_mod.asarray(image).astype(np_mod.float32), 0, 255).astype(np_mod.uint8)


def _resolve_inverse_point(spec: AugmentationSpec) -> InversePointFn:
    if spec.inverse_point is not None:
        return spec.inverse_point
    name = spec.name
    if name in _PIXEL_ONLY_OPS:
        return _inverse_identity
    if name in _D4_OPS:
        return _inverse_d4
    if name in _AFFINE_OP_ANGLE_DEG:
        return _inverse_affine
    return _inverse_identity


def _inverse_quad8_to_original(
    quad8: tuple[float, ...],
    *,
    view: AugmentedView,
) -> tuple[float, ...]:
    out: list[float] = []
    for i in range(0, 8, 2):
        x = _to_float(quad8[i], 0.0)
        y = _to_float(quad8[i + 1], 0.0)
        ox, oy = _inverse_point_to_original(x=x, y=y, view=view)
        out.extend([ox, oy])
    return tuple(out)


def _inverse_point_to_original(
    *,
    x: float,
    y: float,
    view: AugmentedView,
) -> tuple[float, float]:
    try:
        ox, oy = view.inverse_point(float(x), float(y), view)
    except Exception:
        ox, oy = x, y
    if not math.isfinite(ox):
        ox = 0.0
    if not math.isfinite(oy):
        oy = 0.0
    return (
        _clamp(ox, 0.0, float(view.orig_width)),
        _clamp(oy, 0.0, float(view.orig_height)),
    )


def _inverse_identity(x: float, y: float, view: AugmentedView) -> tuple[float, float]:
    del view
    return float(x), float(y)


def _inverse_d4(x: float, y: float, view: AugmentedView) -> tuple[float, float]:
    w = float(view.orig_width)
    h = float(view.orig_height)
    name = view.name
    if name == "hflip":
        return w - x, y
    if name == "vflip":
        return x, h - y
    if name == "rot90":
        return w - y, x
    if name == "rot180":
        return w - x, h - y
    if name == "rot270":
        return y, h - x
    if name == "transpose":
        return y, x
    if name == "transverse":
        return w - y, h - x
    return x, y


def _inverse_affine(x: float, y: float, view: AugmentedView) -> tuple[float, float]:
    angle_deg = float(_AFFINE_OP_ANGLE_DEG.get(view.name, 0.0))
    if angle_deg == 0.0:
        return x, y
    return _rotate_point(
        x=x,
        y=y,
        angle_deg=-angle_deg,
        cx=float(view.orig_width) / 2.0,
        cy=float(view.orig_height) / 2.0,
    )


def _rotate_point(
    *,
    x: float,
    y: float,
    angle_deg: float,
    cx: float,
    cy: float,
) -> tuple[float, float]:
    rad = math.radians(float(angle_deg))
    cos_t = math.cos(rad)
    sin_t = math.sin(rad)
    dx = float(x) - cx
    dy = float(y) - cy
    return (
        dx * cos_t - dy * sin_t + cx,
        dx * sin_t + dy * cos_t + cy,
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _to_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(out):
        return float(default)
    return out


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_unit_float(value: Any, default: float) -> float:
    out = _to_float(value, default)
    return _clamp(out, 0.0, 1.0)


__all__ = [
    "AugmentationSpec",
    "AugmentedView",
    "build_default_augmentation_specs",
    "build_augmented_views",
    "inverse_augmented_prediction_row",
]
