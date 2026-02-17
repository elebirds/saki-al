from __future__ import annotations

"""View/Wrapper 层：仅包裹 proto message，不引入第二模型。

Spec: docs/IR_SPEC.md#13-view-wrapper-guidance
"""

from collections.abc import Iterator

from google.protobuf.message import Message

from . import geom
from .codec import (
    decompress_raw,
    verify_checksum,
    decode_payload,
    iter_items,
)
from .errors import ERR_IR_GEOMETRY, ERR_IR_SCHEMA, IRError
from .normalize import normalize_ir, validate_ir
from .proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1


class EncodedPayloadView:
    """`EncodedPayload` 的只读便利视图。

    设计目标：
    - header/stats 访问不触发 payload decode
    - checksum 校验可独立执行，不需要 protobuf Parse
    - 默认无副作用
    """

    def __init__(self, encoded: annotationirv1.EncodedPayload):
        if encoded is None:
            raise IRError(ERR_IR_SCHEMA, "encoded 不能为空")
        self._encoded = encoded

    @property
    def header(self) -> annotationirv1.PayloadHeader:
        """返回 `PayloadHeader` 副本（copy）。"""

        # Spec: docs/IR_SPEC.md#10-header-only-behavior
        copied = annotationirv1.PayloadHeader()
        if self._encoded.HasField("header"):
            copied.CopyFrom(self._encoded.header)
        return copied

    @property
    def stats(self) -> annotationirv1.PayloadStats:
        """返回 `PayloadStats` 副本（copy）；缺失时返回空 stats。"""

        # Spec: docs/IR_SPEC.md#10-header-only-behavior
        if self._encoded.HasField("header") and self._encoded.header.HasField("stats"):
            copied = annotationirv1.PayloadStats()
            copied.CopyFrom(self._encoded.header.stats)
            return copied
        return annotationirv1.PayloadStats()

    def verify_checksum(self) -> None:
        """仅解压并校验 checksum，不执行 `ParseFromString`。"""

        # Spec: docs/IR_SPEC.md#10-header-only-behavior
        verify_checksum(self._encoded)

    def decompress_raw(self) -> bytes:
        """按 compression 获取 `payload_raw`，不校验 checksum、不 decode。"""

        return decompress_raw(self._encoded)

    def decode(self, *, normalize_output: bool = True) -> annotationirv1.DataBatchIR:
        """解码 payload 到 `DataBatchIR`。

        参数 `normalize_output` 直接透传 `decode_payload`：
        - `True`：返回规范化几何
        - `False`：保留 payload 中的原始几何表示
        """

        return decode_payload(self._encoded, normalize_output=normalize_output)

    def with_header_overrides(self, **kwargs) -> annotationirv1.EncodedPayload:
        """返回修改 header 后的新 EncodedPayload，仅建议用于测试/调试场景。"""

        out = annotationirv1.EncodedPayload()
        out.CopyFrom(self._encoded)

        if not out.HasField("header"):
            out.header.CopyFrom(annotationirv1.PayloadHeader())

        for key, value in kwargs.items():
            if not hasattr(out.header, key):
                raise IRError(ERR_IR_SCHEMA, f"PayloadHeader 不存在字段: {key}")
            current = getattr(out.header, key)
            if isinstance(current, Message):
                if not isinstance(value, Message):
                    raise IRError(ERR_IR_SCHEMA, f"字段 {key} 需要 protobuf Message 类型")
                current.CopyFrom(value)
            else:
                setattr(out.header, key, value)
        return out


class BatchView:
    """`DataBatchIR` 的轻量视图。默认无副作用。"""

    def __init__(self, batch: annotationirv1.DataBatchIR):
        if batch is None:
            raise IRError(ERR_IR_SCHEMA, "batch 不能为空")
        self._batch = batch

    def iter_items(self) -> Iterator[annotationirv1.DataItemIR]:
        """按原始顺序迭代所有 item。"""

        yield from iter_items(self._batch)

    def iter_annotations(self) -> Iterator[AnnotationView]:
        """迭代 annotation item，并包装为 `AnnotationView`。"""

        for item in self._batch.items:
            if item.WhichOneof("item") == "annotation":
                yield AnnotationView(item.annotation)

    def iter_samples(self) -> Iterator[annotationirv1.SampleRecord]:
        """迭代 sample item。"""

        for item in self._batch.items:
            if item.WhichOneof("item") == "sample":
                yield item.sample

    def iter_labels(self) -> Iterator[annotationirv1.LabelRecord]:
        """迭代 label item。"""

        for item in self._batch.items:
            if item.WhichOneof("item") == "label":
                yield item.label

    def normalized_copy(self) -> annotationirv1.DataBatchIR:
        """返回规范化后的新 batch，不修改原输入。"""

        # Spec: docs/IR_SPEC.md#6-obb-normalization
        copied = annotationirv1.DataBatchIR()
        copied.ParseFromString(self._batch.SerializeToString())
        normalize_ir(copied)
        return copied

    def validate(self) -> None:
        """校验 batch，不修改原输入。"""

        validate_ir(self._batch)

    def counts(self) -> dict[str, int]:
        """返回 item/annotation/sample/label 数量（与 payload stats 口径一致）。"""

        item = len(self._batch.items)
        ann = 0
        sample = 0
        label = 0
        for i in self._batch.items:
            kind = i.WhichOneof("item")
            if kind == "annotation":
                ann += 1
            elif kind == "sample":
                sample += 1
            elif kind == "label":
                label += 1
        return {"item": item, "annotation": ann, "sample": sample, "label": label}


class AnnotationView:
    """`AnnotationRecord` 的字段访问视图。"""

    def __init__(self, ann: annotationirv1.AnnotationRecord):
        if ann is None:
            raise IRError(ERR_IR_SCHEMA, "annotation 不能为空")
        self._ann = ann

    @property
    def id(self) -> str:
        """annotation.id。"""

        return self._ann.id

    @property
    def sample_id(self) -> str:
        """annotation.sample_id。"""

        return self._ann.sample_id

    @property
    def label_id(self) -> str:
        """annotation.label_id。"""

        return self._ann.label_id

    @property
    def confidence(self) -> float:
        """annotation.confidence。"""

        return float(self._ann.confidence)

    @property
    def source(self) -> int:
        """annotation.source（枚举值整型）。"""

        return int(self._ann.source)

    def geometry(self) -> GeometryView:
        """返回 geometry 视图。"""

        return GeometryView(self._ann.geometry)

    def shape(self) -> str:
        """返回 `rect` / `obb` / ``。"""

        if not self._ann.HasField("geometry"):
            return ""
        return self._ann.geometry.WhichOneof("shape") or ""


class GeometryView:
    """`Geometry` 的只读计算视图。"""

    def __init__(self, geom_msg: annotationirv1.Geometry):
        if geom_msg is None:
            raise IRError(ERR_IR_SCHEMA, "geometry 不能为空")
        self._geom = geom_msg

    def kind(self) -> str:
        """返回 `rect` / `obb` / ``。"""

        return self._geom.WhichOneof("shape") or ""

    def rect(self) -> RectView | None:
        """若为 rect，返回 `RectView`，否则返回 `None`。"""

        if self.kind() == "rect":
            return RectView(self._geom.rect)
        return None

    def obb(self) -> ObbView | None:
        """若为 obb，返回 `ObbView`，否则返回 `None`。"""

        if self.kind() == "obb":
            return ObbView(self._geom.obb)
        return None

    def vertices(self) -> list[tuple[float, float]]:
        """返回 4 顶点。

        rect/obb 都返回 `TL, TR, BR, BL`。其中 OBB 的 TL/TR/BR/BL 是局部角点顺序，
        不是按屏幕坐标排序。
        """

        # Spec: docs/IR_SPEC.md#7-vertices-and-aabb
        kind = self.kind()
        if kind == "rect":
            return geom.rect_to_vertices(self._geom.rect)
        if kind == "obb":
            return geom.obb_to_vertices(self._geom.obb)
        raise IRError(ERR_IR_GEOMETRY, "geometry.shape 缺失")

    def aabb_rect_tl(self) -> tuple[float, float, float, float]:
        """返回 AABB 的 `(x, y, w, h)`，由顶点 min/max 计算。"""

        # Spec: docs/IR_SPEC.md#7-vertices-and-aabb
        kind = self.kind()
        if kind == "rect":
            r = self._geom.rect
            return float(r.x), float(r.y), float(r.width), float(r.height)
        if kind == "obb":
            vertices = self.vertices()
            xs = [p[0] for p in vertices]
            ys = [p[1] for p in vertices]
            x0 = min(xs)
            y0 = min(ys)
            x1 = max(xs)
            y1 = max(ys)
            return x0, y0, x1 - x0, y1 - y0
        raise IRError(ERR_IR_GEOMETRY, "geometry.shape 缺失")


class RectView:
    """`RectGeometry` 的只读视图。"""

    def __init__(self, rect: annotationirv1.RectGeometry):
        if rect is None:
            raise IRError(ERR_IR_SCHEMA, "rect 不能为空")
        self._rect = rect

    def tlwh(self) -> tuple[float, float, float, float]:
        """返回 `(x, y, w, h)`。"""

        return float(self._rect.x), float(self._rect.y), float(self._rect.width), float(self._rect.height)

    def center(self) -> tuple[float, float, float, float]:
        """返回中心语义 `(cx, cy, w, h)`。"""

        return geom.rect_tl_to_center(self._rect)

    def vertices(self) -> list[tuple[float, float]]:
        """返回顶点 `TL, TR, BR, BL`。"""

        return geom.rect_to_vertices(self._rect)


class ObbView:
    """`ObbGeometry` 的只读视图。"""

    def __init__(self, obb: annotationirv1.ObbGeometry):
        if obb is None:
            raise IRError(ERR_IR_SCHEMA, "obb 不能为空")
        self._obb = obb

    def center(self) -> tuple[float, float, float, float, float]:
        """返回 `(cx, cy, w, h, angle_deg_cw)`。"""

        return (
            float(self._obb.cx),
            float(self._obb.cy),
            float(self._obb.width),
            float(self._obb.height),
            float(self._obb.angle_deg_cw),
        )

    def vertices(self) -> list[tuple[float, float]]:
        """返回 OBB 顶点 `TL, TR, BR, BL`（局部角点顺序）。"""

        return geom.obb_to_vertices(self._obb)
