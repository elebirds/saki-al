from __future__ import annotations

"""转换模块公共基础设施。"""

from dataclasses import dataclass, field
import math
from typing import Any
import warnings
from uuid import uuid4

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1


ERR_CONVERT_SCHEMA = "ERR_CONVERT_SCHEMA"
ERR_CONVERT_IO = "ERR_CONVERT_IO"
ERR_CONVERT_GEOMETRY = "ERR_CONVERT_GEOMETRY"
ERR_CONVERT_UNSUPPORTED = "ERR_CONVERT_UNSUPPORTED"


class ConversionError(Exception):
    """转换错误。

    Attributes:
        code: 稳定错误码。
        message: 面向开发者的错误信息。
        source_ref: 可选来源引用（文件/行号/外部 id）。
    """

    def __init__(self, code: str, message: str, source_ref: str | None = None):
        self.code = code
        self.message = message
        self.source_ref = source_ref
        super().__init__(self.__str__())

    def __str__(self) -> str:
        if self.source_ref:
            return f"{self.code}: {self.message} (source_ref={self.source_ref})"
        return f"{self.code}: {self.message}"


@dataclass
class ConversionReport:
    """转换过程报告。"""

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def raise_or_record(self, err: ConversionError, *, strict: bool) -> None:
        if strict:
            raise err
        self.errors.append(str(err))


@dataclass
class ConversionContext:
    """转换上下文配置。"""

    strict: bool = True
    include_external_ref: bool = True
    emit_labels: bool = True
    clip_on_export: bool = True
    eps: float = 1e-6

    # YOLO
    yolo_is_normalized: bool = True
    yolo_float_precision: int = 6

    # VOC
    voc_coord_base: int = 0  # 0 or 1

    # IO
    naming: str = "keep_external"  # or "uuid"
    read_images: bool = True
    max_samples: int | None = None
    batch_mode: str = "single"  # "single" or "per_sample"


def make_report(
    report: ConversionReport | None = None,
    *,
    strict: bool | None = None,
) -> ConversionReport:
    """返回可用的 ConversionReport。

    注意：若调用方不传入 report，本函数会创建临时 report，仅用于函数内部
    strict=False 的继续执行；调用方无法在函数返回后读取其中的 warnings/errors。
    """

    if report is None and strict is False:
        warnings.warn(
            "strict=False 但未传入 report；warnings/errors 将不会返回给调用方",
            stacklevel=2,
        )
    return report if report is not None else ConversionReport()


def fail_or_report(
    *,
    ctx: ConversionContext,
    report: ConversionReport,
    code: str,
    message: str,
    source_ref: str | None = None,
) -> None:
    report.raise_or_record(ConversionError(code=code, message=message, source_ref=source_ref), strict=ctx.strict)


def new_uuid() -> str:
    """生成 uuid4 字符串。"""

    return str(uuid4())


def dict_to_struct(d: dict[str, Any]) -> Struct:
    """将 dict 转为 protobuf Struct。

    约定：`meta/attrs.external` 只用于排障与来源追踪，不保证稳定 schema。
    """

    struct = Struct()
    if d:
        ParseDict(d, struct)
    return struct


def struct_to_dict(s: Struct | None) -> dict[str, Any]:
    """将 protobuf Struct 转为 dict。

    约定：`meta/attrs.external` 只用于排障与来源追踪，不应作为业务主键。
    """

    if s is None:
        return {}
    return MessageToDict(s, preserving_proto_field_name=True)


def is_finite(*values: float) -> bool:
    """判断一组数值是否均为有限值。"""

    try:
        return all(math.isfinite(float(v)) for v in values)
    except (TypeError, ValueError):
        return False


def tlwh_to_tlbr(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    return x, y, x + w, y + h


def tlbr_to_tlwh(xmin: float, ymin: float, xmax: float, ymax: float) -> tuple[float, float, float, float]:
    return xmin, ymin, xmax - xmin, ymax - ymin


def rect_ir_to_yolo(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    image_w: int,
    image_h: int,
    normalized: bool,
) -> tuple[float, float, float, float]:
    """IR TLWH -> YOLO center。"""

    cx = x + w / 2.0
    cy = y + h / 2.0
    if normalized:
        return cx / float(image_w), cy / float(image_h), w / float(image_w), h / float(image_h)
    return cx, cy, w, h


def yolo_to_rect_ir(
    cx: float,
    cy: float,
    w: float,
    h: float,
    *,
    image_w: int,
    image_h: int,
    normalized: bool,
) -> tuple[float, float, float, float]:
    """YOLO center -> IR TLWH。"""

    if normalized:
        ww = w * float(image_w)
        hh = h * float(image_h)
        x = (cx - w / 2.0) * float(image_w)
        y = (cy - h / 2.0) * float(image_h)
        return x, y, ww, hh

    return cx - w / 2.0, cy - h / 2.0, w, h


def clip_tlwh_to_image(
    x: float,
    y: float,
    w: float,
    h: float,
    image_w: int,
    image_h: int,
) -> tuple[float, float, float, float]:
    """将 TLWH 裁剪到图像边界。

    坐标语义是“连续像素坐标”（非离散像素索引），因此 clamp 到闭区间
    `[0, image_w] x [0, image_h]`。若完全在图像外，返回 w/h=0。
    """

    x0, y0, x1, y1 = tlwh_to_tlbr(x, y, w, h)
    x0 = max(0.0, min(float(image_w), x0))
    y0 = max(0.0, min(float(image_h), y0))
    x1 = max(0.0, min(float(image_w), x1))
    y1 = max(0.0, min(float(image_h), y1))

    if x1 < x0:
        x1 = x0
    if y1 < y0:
        y1 = y0
    return tlbr_to_tlwh(x0, y0, x1, y1)


def build_batch(
    labels: list[annotationirv1.LabelRecord] | None,
    samples: list[annotationirv1.SampleRecord] | None,
    annotations: list[annotationirv1.AnnotationRecord] | None,
) -> annotationirv1.DataBatchIR:
    """按固定顺序构建 batch：labels -> samples -> annotations。"""

    batch = annotationirv1.DataBatchIR()

    for label in labels or []:
        item = batch.items.add()
        item.label.CopyFrom(label)

    for sample in samples or []:
        item = batch.items.add()
        item.sample.CopyFrom(sample)

    for ann in annotations or []:
        item = batch.items.add()
        item.annotation.CopyFrom(ann)

    return batch


def split_batch(
    batch: annotationirv1.DataBatchIR,
    *,
    ctx: ConversionContext | None = None,
    report: ConversionReport | None = None,
    source_ref: str = "batch.items",
    unknown_item_policy: str = "warn",
) -> tuple[dict[str, annotationirv1.LabelRecord], list[annotationirv1.SampleRecord], list[annotationirv1.AnnotationRecord]]:
    """统一拆分 batch 为 labels/samples/annotations。

    返回：
    - labels_by_id: label.id -> LabelRecord
    - samples: SampleRecord 列表（保持原顺序）
    - annotations: AnnotationRecord 列表（保持原顺序）

    若存在未知 oneof（包括空 item）：
    - `unknown_item_policy=\"warn\"`：记录 warning 并跳过（推荐默认）；
    - `unknown_item_policy=\"error\"`：按 `fail_or_report` 处理；
    - 否则静默跳过。
    """

    labels_by_id: dict[str, annotationirv1.LabelRecord] = {}
    samples: list[annotationirv1.SampleRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []

    for idx, item in enumerate(batch.items):
        kind = item.WhichOneof("item")
        if kind == "label":
            labels_by_id[item.label.id] = item.label
            continue
        if kind == "sample":
            samples.append(item.sample)
            continue
        if kind == "annotation":
            annotations.append(item.annotation)
            continue

        if ctx is not None and report is not None and unknown_item_policy == "error":
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="DataItemIR.item 缺失或未知",
                source_ref=f"{source_ref}[{idx}]",
            )
        elif report is not None:
            report.warn(f"{source_ref}[{idx}]: DataItemIR.item 缺失或未知，已跳过")

    return labels_by_id, samples, annotations


def require_single_sample(
    samples: list[annotationirv1.SampleRecord],
    *,
    ctx: ConversionContext,
    report: ConversionReport,
    source_ref: str,
    target_name: str,
) -> annotationirv1.SampleRecord | None:
    """校验导出目标仅接受单 sample。"""

    if len(samples) != 1:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"{target_name} 导出要求 batch 内恰好 1 个 sample，当前={len(samples)}",
            source_ref=source_ref,
        )
        return None
    return samples[0]


def maybe_clip_rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    sample: annotationirv1.SampleRecord,
    ctx: ConversionContext,
    report: ConversionReport,
    source_ref: str,
) -> tuple[float, float, float, float] | None:
    """导出阶段统一处理 clip 与几何合法性校验。

    返回：
    - `(x, y, w, h)`：可继续导出
    - `None`：当前框需跳过（strict=False）或已抛错（strict=True）
    """

    if ctx.clip_on_export:
        if sample.width <= 0 or sample.height <= 0:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="clip_on_export=True 但 sample 缺失有效图像尺寸",
                source_ref=source_ref,
            )
            return None
        x, y, w, h = clip_tlwh_to_image(x, y, w, h, int(sample.width), int(sample.height))

    if not validate_rect(x, y, w, h, ctx=ctx, report=report, source_ref=source_ref):
        return None

    return x, y, w, h


def validate_rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    ctx: ConversionContext,
    report: ConversionReport,
    source_ref: str,
) -> bool:
    """校验 TLWH 是否满足几何约束。"""

    if not is_finite(x, y, w, h) or w <= ctx.eps or h <= ctx.eps:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_GEOMETRY,
            message=f"导出框非法: x={x}, y={y}, w={w}, h={h}",
            source_ref=source_ref,
        )
        return False
    return True


def make_external_meta(
    *,
    source: str,
    sample_key: str | None = None,
    file_name: str | None = None,
    relpath: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": source}
    if sample_key is not None:
        meta["sample_key"] = sample_key
    if file_name is not None:
        meta["file_name"] = file_name
    if relpath is not None:
        meta["relpath"] = relpath
    return meta


def make_external_attrs(
    *,
    ann_key: str | None = None,
    category_key: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if ann_key is not None:
        attrs["ann_key"] = ann_key
    if category_key is not None:
        attrs["category_key"] = category_key
    if line is not None:
        attrs["line"] = line
    return attrs
