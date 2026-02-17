from __future__ import annotations

import math

from saki_ir.errors import ERR_IR_GEOMETRY, ERR_IR_SCHEMA, IRError
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

EPS = 1e-6


def _is_finite(*values: float) -> bool:
    return all(math.isfinite(float(v)) for v in values)


def _normalize_angle_deg_cw(angle_deg_cw: float) -> float:
    angle = (float(angle_deg_cw) + 180.0) % 360.0 - 180.0
    # 统一把 180 归到 -180，满足 [-180, 180)
    if angle >= 180.0:
        angle -= 360.0
    return angle


def _normalize_rect(rect: annotationirv1.RectGeometry, idx: int) -> None:
    if not _is_finite(rect.x, rect.y, rect.width, rect.height):
        raise IRError(ERR_IR_GEOMETRY, f"annotation[{idx}] rect 含 NaN/Inf")
    if rect.width <= EPS or rect.height <= EPS:
        raise IRError(ERR_IR_GEOMETRY, f"annotation[{idx}] rect width/height 必须 > {EPS}")


def _normalize_obb(obb: annotationirv1.ObbGeometry, idx: int) -> None:
    if not _is_finite(obb.cx, obb.cy, obb.width, obb.height, obb.angle_deg_cw):
        raise IRError(ERR_IR_GEOMETRY, f"annotation[{idx}] obb 含 NaN/Inf")
    if obb.width <= EPS or obb.height <= EPS:
        raise IRError(ERR_IR_GEOMETRY, f"annotation[{idx}] obb width/height 必须 > {EPS}")

    if obb.width < obb.height:
        obb.width, obb.height = obb.height, obb.width
        obb.angle_deg_cw = float(obb.angle_deg_cw) + 90.0

    obb.angle_deg_cw = _normalize_angle_deg_cw(obb.angle_deg_cw)


def _validate_confidence(confidence: float, idx: int) -> None:
    if not _is_finite(confidence):
        raise IRError(ERR_IR_SCHEMA, f"annotation[{idx}] confidence 含 NaN/Inf")
    if confidence < 0.0 or confidence > 1.0:
        raise IRError(ERR_IR_SCHEMA, f"annotation[{idx}] confidence 必须在 [0,1]")


def normalize_ir(batch: annotationirv1.DataBatchIR) -> annotationirv1.DataBatchIR:
    """原地规范化 batch 并返回同一个对象。"""

    if batch is None:
        raise IRError(ERR_IR_SCHEMA, "batch 不能为空")

    for idx, item in enumerate(batch.items):
        kind = item.WhichOneof("item")
        if kind != "annotation":
            continue

        ann = item.annotation
        _validate_confidence(float(ann.confidence), idx)

        if not ann.HasField("geometry"):
            raise IRError(ERR_IR_GEOMETRY, f"annotation[{idx}] geometry 缺失")

        shape = ann.geometry.WhichOneof("shape")
        if shape == "rect":
            _normalize_rect(ann.geometry.rect, idx)
        elif shape == "obb":
            _normalize_obb(ann.geometry.obb, idx)
        else:
            raise IRError(ERR_IR_GEOMETRY, f"annotation[{idx}] geometry.shape 缺失")

    return batch


def validate_ir(batch: annotationirv1.DataBatchIR) -> None:
    """校验 batch，不修改输入。"""

    if batch is None:
        raise IRError(ERR_IR_SCHEMA, "batch 不能为空")

    copied = annotationirv1.DataBatchIR()
    copied.ParseFromString(batch.SerializeToString())
    normalize_ir(copied)
