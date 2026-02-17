from __future__ import annotations

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
    def __init__(self, encoded: annotationirv1.EncodedPayload):
        if encoded is None:
            raise IRError(ERR_IR_SCHEMA, "encoded 不能为空")
        self._encoded = encoded

    @property
    def header(self) -> annotationirv1.PayloadHeader:
        copied = annotationirv1.PayloadHeader()
        if self._encoded.HasField("header"):
            copied.CopyFrom(self._encoded.header)
        return copied

    @property
    def stats(self) -> annotationirv1.PayloadStats:
        if self._encoded.HasField("header") and self._encoded.header.HasField("stats"):
            copied = annotationirv1.PayloadStats()
            copied.CopyFrom(self._encoded.header.stats)
            return copied
        return annotationirv1.PayloadStats()

    def verify_checksum(self) -> None:
        verify_checksum(self._encoded)

    def decompress_raw(self) -> bytes:
        return decompress_raw(self._encoded)

    def decode(self, *, normalize_output: bool = True) -> annotationirv1.DataBatchIR:
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
    def __init__(self, batch: annotationirv1.DataBatchIR):
        if batch is None:
            raise IRError(ERR_IR_SCHEMA, "batch 不能为空")
        self._batch = batch

    def iter_items(self) -> Iterator[annotationirv1.DataItemIR]:
        yield from iter_items(self._batch)

    def iter_annotations(self) -> Iterator[AnnotationView]:
        for item in self._batch.items:
            if item.WhichOneof("item") == "annotation":
                yield AnnotationView(item.annotation)

    def iter_samples(self) -> Iterator[annotationirv1.SampleRecord]:
        for item in self._batch.items:
            if item.WhichOneof("item") == "sample":
                yield item.sample

    def iter_labels(self) -> Iterator[annotationirv1.LabelRecord]:
        for item in self._batch.items:
            if item.WhichOneof("item") == "label":
                yield item.label

    def normalized_copy(self) -> annotationirv1.DataBatchIR:
        copied = annotationirv1.DataBatchIR()
        copied.ParseFromString(self._batch.SerializeToString())
        normalize_ir(copied)
        return copied

    def validate(self) -> None:
        validate_ir(self._batch)

    def counts(self) -> dict[str, int]:
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
    def __init__(self, ann: annotationirv1.AnnotationRecord):
        if ann is None:
            raise IRError(ERR_IR_SCHEMA, "annotation 不能为空")
        self._ann = ann

    @property
    def id(self) -> str:
        return self._ann.id

    @property
    def sample_id(self) -> str:
        return self._ann.sample_id

    @property
    def label_id(self) -> str:
        return self._ann.label_id

    @property
    def confidence(self) -> float:
        return float(self._ann.confidence)

    @property
    def source(self) -> int:
        return int(self._ann.source)

    def geometry(self) -> GeometryView:
        return GeometryView(self._ann.geometry)

    def shape(self) -> str:
        if not self._ann.HasField("geometry"):
            return ""
        return self._ann.geometry.WhichOneof("shape") or ""


class GeometryView:
    def __init__(self, geom_msg: annotationirv1.Geometry):
        if geom_msg is None:
            raise IRError(ERR_IR_SCHEMA, "geometry 不能为空")
        self._geom = geom_msg

    def kind(self) -> str:
        return self._geom.WhichOneof("shape") or ""

    def rect(self) -> RectView | None:
        if self.kind() == "rect":
            return RectView(self._geom.rect)
        return None

    def obb(self) -> ObbView | None:
        if self.kind() == "obb":
            return ObbView(self._geom.obb)
        return None

    def vertices(self) -> list[tuple[float, float]]:
        kind = self.kind()
        if kind == "rect":
            return geom.rect_to_vertices(self._geom.rect)
        if kind == "obb":
            return geom.obb_to_vertices(self._geom.obb)
        raise IRError(ERR_IR_GEOMETRY, "geometry.shape 缺失")

    def aabb_rect_tl(self) -> tuple[float, float, float, float]:
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
    def __init__(self, rect: annotationirv1.RectGeometry):
        if rect is None:
            raise IRError(ERR_IR_SCHEMA, "rect 不能为空")
        self._rect = rect

    def tlwh(self) -> tuple[float, float, float, float]:
        return float(self._rect.x), float(self._rect.y), float(self._rect.width), float(self._rect.height)

    def center(self) -> tuple[float, float, float, float]:
        return geom.rect_tl_to_center(self._rect)

    def vertices(self) -> list[tuple[float, float]]:
        return geom.rect_to_vertices(self._rect)


class ObbView:
    def __init__(self, obb: annotationirv1.ObbGeometry):
        if obb is None:
            raise IRError(ERR_IR_SCHEMA, "obb 不能为空")
        self._obb = obb

    def center(self) -> tuple[float, float, float, float, float]:
        return (
            float(self._obb.cx),
            float(self._obb.cy),
            float(self._obb.width),
            float(self._obb.height),
            float(self._obb.angle_deg_cw),
        )

    def vertices(self) -> list[tuple[float, float]]:
        return geom.obb_to_vertices(self._obb)
