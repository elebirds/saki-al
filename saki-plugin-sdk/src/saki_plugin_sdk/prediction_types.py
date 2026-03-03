"""Prediction candidate schema validation utilities."""

from __future__ import annotations

from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict

from saki_ir import normalize_ir
from saki_ir.errors import IRError
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb


def _to_float(value: Any, *, field: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"{field} must be a number") from exc


def _normalize_geometry_with_ir(value: Any, *, prefix: str, confidence: float) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{prefix}.geometry must be an object")
    geometry = irpb.Geometry()
    try:
        ParseDict(dict(value), geometry, ignore_unknown_fields=False)
    except Exception as exc:
        raise ValueError(f"{prefix}.geometry is invalid: {exc}") from exc

    if geometry.WhichOneof("shape") not in {"rect", "obb"}:
        raise ValueError(f"{prefix}.geometry.shape is required and must be rect or obb")

    batch = irpb.DataBatchIR(
        items=[
            irpb.DataItemIR(
                annotation=irpb.AnnotationRecord(
                    id="__prediction_validation__",
                    sample_id="__prediction_validation__",
                    label_id="__prediction_validation__",
                    geometry=geometry,
                    source=irpb.ANNOTATION_SOURCE_MODEL,
                    confidence=float(confidence),
                )
            )
        ]
    )
    try:
        normalize_ir(batch)
    except IRError as exc:
        raise ValueError(f"{prefix}.geometry is invalid: {exc.message}") from exc
    normalized = batch.items[0].annotation.geometry
    return dict(MessageToDict(normalized, preserving_proto_field_name=True))


def _normalize_prediction_entry(entry: Any, *, prefix: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"{prefix} must be an object")
    row = dict(entry)
    if "class_index" not in row:
        raise ValueError(f"{prefix}.class_index is required")
    try:
        class_index = int(row.get("class_index"))
    except Exception as exc:
        raise ValueError(f"{prefix}.class_index must be an integer") from exc
    if class_index < 0:
        raise ValueError(f"{prefix}.class_index must be >= 0")

    if "confidence" not in row:
        raise ValueError(f"{prefix}.confidence is required")
    confidence = _to_float(row.get("confidence"), field=f"{prefix}.confidence")
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"{prefix}.confidence must be in [0, 1]")

    if "geometry" not in row:
        raise ValueError(f"{prefix}.geometry is required")
    geometry = _normalize_geometry_with_ir(row.get("geometry"), prefix=prefix, confidence=confidence)

    class_name_raw = row.get("class_name")
    class_name: str | None = None
    if class_name_raw is not None:
        class_name = str(class_name_raw).strip() or None

    label_id_raw = row.get("label_id")
    label_id: str | None = None
    if label_id_raw is not None:
        label_id = str(label_id_raw).strip() or None

    attrs_raw = row.get("attrs")
    attrs = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}

    normalized: dict[str, Any] = {
        "class_index": class_index,
        "confidence": confidence,
        "geometry": geometry,
    }
    if class_name is not None:
        normalized["class_name"] = class_name
    if label_id is not None:
        normalized["label_id"] = label_id
    if attrs:
        normalized["attrs"] = attrs
    return normalized


def _normalize_snapshot(snapshot: Any, *, prefix: str) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError(f"{prefix} must be an object")
    payload = dict(snapshot)
    for key in ("base_predictions", "predictions"):
        if key not in payload:
            continue
        items = payload.get(key)
        if not isinstance(items, list):
            raise ValueError(f"{prefix}.{key} must be a list")
        payload[key] = [
            _normalize_prediction_entry(item, prefix=f"{prefix}.{key}[{idx}]")
            for idx, item in enumerate(items)
        ]
    return payload


def normalize_prediction_candidates(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"candidate[{idx}] must be an object")
        row = dict(raw)
        sample_id = str(row.get("sample_id") or "").strip()
        if not sample_id:
            raise ValueError(f"candidate[{idx}].sample_id is required")
        row["sample_id"] = sample_id
        row["score"] = _to_float(row.get("score") or 0.0, field=f"candidate[{idx}].score")

        reason_raw = row.get("reason")
        if reason_raw is None:
            reason: dict[str, Any] = {}
        elif isinstance(reason_raw, dict):
            reason = dict(reason_raw)
        else:
            raise ValueError(f"candidate[{idx}].reason must be an object")

        top_snapshot_raw = row.get("prediction_snapshot")
        reason_snapshot_raw = reason.get("prediction_snapshot")
        if top_snapshot_raw is not None and reason_snapshot_raw is not None and top_snapshot_raw != reason_snapshot_raw:
            raise ValueError(f"candidate[{idx}].prediction_snapshot conflicts with candidate[{idx}].reason.prediction_snapshot")

        snapshot_raw = top_snapshot_raw if top_snapshot_raw is not None else reason_snapshot_raw
        if snapshot_raw is not None:
            snapshot = _normalize_snapshot(snapshot_raw, prefix=f"candidate[{idx}].prediction_snapshot")
            row["prediction_snapshot"] = snapshot
            reason["prediction_snapshot"] = snapshot

        row["reason"] = reason
        normalized.append(row)
    return normalized
