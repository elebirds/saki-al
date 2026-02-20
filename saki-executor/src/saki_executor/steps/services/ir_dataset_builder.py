from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from saki_executor.agent import codec as runtime_codec
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb


@dataclass(frozen=True)
class IRDatasetBuildReport:
    label_count: int
    sample_count: int
    annotation_count: int
    dropped_annotation_count: int


_ANNOTATION_SOURCE_MAP: dict[str, int] = {
    "manual": irpb.ANNOTATION_SOURCE_MANUAL,
    "model": irpb.ANNOTATION_SOURCE_MODEL,
    "system": irpb.ANNOTATION_SOURCE_SYSTEM,
    "imported": irpb.ANNOTATION_SOURCE_IMPORTED,
}


def build_training_batch_ir(
    *,
    labels: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
) -> tuple[irpb.DataBatchIR, IRDatasetBuildReport]:
    batch = irpb.DataBatchIR()

    label_records: list[irpb.LabelRecord] = []
    label_ids: set[str] = set()
    for item in labels:
        label_id = str(item.get("id") or "").strip()
        if not label_id or label_id in label_ids:
            continue
        label_ids.add(label_id)
        label_records.append(
            irpb.LabelRecord(
                id=label_id,
                name=str(item.get("name") or label_id),
                color=str(item.get("color") or ""),
            )
        )

    sample_records: list[irpb.SampleRecord] = []
    sample_dims: dict[str, tuple[int, int]] = {}
    for item in samples:
        sample_id = str(item.get("id") or "").strip()
        if not sample_id:
            continue
        width = max(0, _to_int(item.get("width"), 0))
        height = max(0, _to_int(item.get("height"), 0))
        sample_dims[sample_id] = (width, height)

        sample_meta = dict(item.get("meta") or {}) if isinstance(item.get("meta"), dict) else {}
        local_path = str(item.get("local_path") or "").strip()
        if local_path:
            runtime_meta = sample_meta.get("runtime")
            if not isinstance(runtime_meta, dict):
                runtime_meta = {}
            runtime_meta["local_path"] = local_path
            sample_meta["runtime"] = runtime_meta

        sample_records.append(
            irpb.SampleRecord(
                id=sample_id,
                asset_hash=str(item.get("asset_hash") or ""),
                download_url=str(item.get("download_url") or ""),
                width=width,
                height=height,
                meta=runtime_codec.dict_to_struct(sample_meta),
            )
        )

    annotation_records: list[irpb.AnnotationRecord] = []
    dropped_annotation_count = 0
    for index, item in enumerate(annotations):
        sample_id = str(item.get("sample_id") or "").strip()
        label_id = str(item.get("category_id") or item.get("label_id") or "").strip()
        if not sample_id or not label_id:
            dropped_annotation_count += 1
            continue

        geometry = _build_geometry(item=item, sample_dims=sample_dims.get(sample_id))
        if geometry is None:
            dropped_annotation_count += 1
            continue

        confidence = _to_float(item.get("confidence"), 1.0)
        if not isfinite(confidence):
            confidence = 1.0

        source_raw = str(item.get("source") or "").strip().lower()
        source = _ANNOTATION_SOURCE_MAP.get(
            source_raw,
            getattr(irpb, "ANNOTATION_SOURCE_UNSPECIFIED", 0),
        )

        annotation_id = str(item.get("id") or "").strip() or f"{sample_id}:{label_id}:{index + 1}"
        annotation_records.append(
            irpb.AnnotationRecord(
                id=annotation_id,
                sample_id=sample_id,
                label_id=label_id,
                source=source,
                confidence=confidence,
                geometry=geometry,
            )
        )

    for record in label_records:
        item = batch.items.add()
        item.label.CopyFrom(record)

    for record in sample_records:
        item = batch.items.add()
        item.sample.CopyFrom(record)

    for record in annotation_records:
        item = batch.items.add()
        item.annotation.CopyFrom(record)

    return batch, IRDatasetBuildReport(
        label_count=len(label_records),
        sample_count=len(sample_records),
        annotation_count=len(annotation_records),
        dropped_annotation_count=dropped_annotation_count,
    )


def _build_geometry(
    *,
    item: dict[str, Any],
    sample_dims: tuple[int, int] | None,
) -> irpb.Geometry | None:
    obb = item.get("obb")
    if isinstance(obb, dict):
        cx = _to_float_or_none(obb.get("cx"))
        cy = _to_float_or_none(obb.get("cy"))
        width = _to_float_or_none(obb.get("width", obb.get("w")))
        height = _to_float_or_none(obb.get("height", obb.get("h")))
        angle = _to_float_or_none(obb.get("angle_deg_ccw", obb.get("angle_deg", obb.get("angle"))))
        if cx is None or cy is None or width is None or height is None:
            return None

        if _to_bool(obb.get("normalized"), False):
            image_w = int(sample_dims[0]) if sample_dims else 0
            image_h = int(sample_dims[1]) if sample_dims else 0
            if image_w <= 0 or image_h <= 0:
                return None
            cx *= float(image_w)
            cy *= float(image_h)
            width *= float(image_w)
            height *= float(image_h)

        if width > 0 and height > 0:
            return irpb.Geometry(
                obb=irpb.ObbGeometry(
                    cx=cx,
                    cy=cy,
                    width=width,
                    height=height,
                    angle_deg_ccw=angle if angle is not None else 0.0,
                )
            )

    bbox = item.get("bbox_xywh")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        x = _to_float_or_none(bbox[0])
        y = _to_float_or_none(bbox[1])
        width = _to_float_or_none(bbox[2])
        height = _to_float_or_none(bbox[3])
        if x is None or y is None or width is None or height is None:
            return None
        if width > 0 and height > 0:
            return irpb.Geometry(
                rect=irpb.RectGeometry(
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                )
            )

    return None


def _to_float_or_none(value: Any) -> float | None:
    try:
        output = float(value)
    except Exception:
        return None
    if not isfinite(output):
        return None
    return output


def _to_float(value: Any, default: float) -> float:
    output = _to_float_or_none(value)
    if output is None:
        return default
    return output


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
