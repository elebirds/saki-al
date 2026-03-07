from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict

from saki_ir.errors import IRError
from saki_ir.normalize import normalize_ir
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb

from .errors import IRValidationError, IRValidationIssue
from .geometry import parse_geometry

IR_PREDICTION_FIELD_MISSING = "IR_PREDICTION_FIELD_MISSING"
IR_PREDICTION_FIELD_TYPE = "IR_PREDICTION_FIELD_TYPE"
IR_PREDICTION_CONFLICT = "IR_PREDICTION_CONFLICT"
IR_UNSUPPORTED_LEGACY_FIELD = "IR_UNSUPPORTED_LEGACY_FIELD"

_ALLOWED_ENTRY_FIELDS = {
    "class_index",
    "class_name",
    "confidence",
    "geometry",
    "label_id",
    "attrs",
}
_LEGACY_ENTRY_FIELDS = {
    "cls_id",
    "class_id",
    "category_id",
    "conf",
    "xyxy",
    "bbox_xywh",
}
_LEGACY_SNAPSHOT_FIELDS = {"predictionSnapshot", "top_prediction"}
_ANNOTATION_INDEX_RE = re.compile(r"annotation\[(\d+)\]")


def _preview(value: Any) -> str:
    try:
        text = repr(value)
    except Exception:
        text = "<unreprable>"
    if len(text) <= 160:
        return text
    return text[:157] + "..."


def _single_issue_error(
    *,
    code: str,
    path: str,
    message: str,
    hint: str = "",
    value_preview: str = "",
) -> IRValidationError:
    return IRValidationError(
        [
            IRValidationIssue(
                code=code,
                path=path,
                message=message,
                hint=hint,
                value_preview=value_preview,
            )
        ]
    )


def _require_mapping(value: Any, *, path: str, message: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    raise _single_issue_error(
        code=IR_PREDICTION_FIELD_TYPE,
        path=path,
        message=message,
        hint="provide a JSON object",
        value_preview=_preview(value),
    )


def _ensure_no_legacy_keys(payload: Mapping[str, Any], *, path: str, allowed_keys: set[str]) -> None:
    for key in payload.keys():
        text = str(key)
        if text in _LEGACY_ENTRY_FIELDS or text in _LEGACY_SNAPSHOT_FIELDS:
            raise _single_issue_error(
                code=IR_UNSUPPORTED_LEGACY_FIELD,
                path=f"{path}.{text}",
                message=f"legacy field '{text}' is not supported",
                hint="use class_index/class_name/confidence/geometry contract",
            )
        if text not in allowed_keys:
            raise _single_issue_error(
                code=IR_PREDICTION_FIELD_TYPE,
                path=f"{path}.{text}",
                message=f"unsupported field '{text}'",
                hint=f"allowed fields: {sorted(allowed_keys)}",
            )


def _parse_class_index(raw: Any, *, path: str) -> int:
    if raw is None:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_MISSING,
            path=path,
            message="class_index is required",
        )
    try:
        value = int(raw)
    except Exception as exc:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path=path,
            message="class_index must be an integer",
            value_preview=_preview(raw),
        ) from exc
    if value < 0:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path=path,
            message="class_index must be >= 0",
            value_preview=_preview(raw),
        )
    return value


def _parse_confidence(raw: Any, *, path: str) -> float:
    if raw is None:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_MISSING,
            path=path,
            message="confidence is required",
        )
    try:
        value = float(raw)
    except Exception as exc:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path=path,
            message="confidence must be a number",
            value_preview=_preview(raw),
        ) from exc
    if not math.isfinite(value):
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path=path,
            message="confidence must be finite",
            value_preview=_preview(raw),
        )
    if value < 0.0 or value > 1.0:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path=path,
            message="confidence must be in [0, 1]",
            value_preview=_preview(raw),
        )
    return value


def _normalize_optional_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _extract_error_index(exc: IRError) -> int | None:
    match = _ANNOTATION_INDEX_RE.search(str(exc.message))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _normalize_entries(entries: list[dict[str, Any]], *, path: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    batch_items: list[irpb.DataItemIR] = []
    for idx, raw_entry in enumerate(entries):
        entry_path = f"{path}[{idx}]"
        row = _require_mapping(raw_entry, path=entry_path, message=f"{entry_path} must be an object")
        _ensure_no_legacy_keys(row, path=entry_path, allowed_keys=_ALLOWED_ENTRY_FIELDS)

        class_index = _parse_class_index(row.get("class_index"), path=f"{entry_path}.class_index")
        confidence = _parse_confidence(row.get("confidence"), path=f"{entry_path}.confidence")
        if "geometry" not in row:
            raise _single_issue_error(
                code=IR_PREDICTION_FIELD_MISSING,
                path=f"{entry_path}.geometry",
                message="geometry is required",
            )
        geometry = parse_geometry(_require_mapping(row.get("geometry"), path=f"{entry_path}.geometry", message=f"{entry_path}.geometry must be an object"))

        class_name = _normalize_optional_text(row.get("class_name"))
        label_id = _normalize_optional_text(row.get("label_id"))
        attrs_raw = row.get("attrs")
        if attrs_raw is None:
            attrs: dict[str, Any] = {}
        elif isinstance(attrs_raw, Mapping):
            attrs = dict(attrs_raw)
        else:
            raise _single_issue_error(
                code=IR_PREDICTION_FIELD_TYPE,
                path=f"{entry_path}.attrs",
                message="attrs must be an object",
                value_preview=_preview(attrs_raw),
            )

        parsed.append(
            {
                "class_index": class_index,
                "class_name": class_name,
                "label_id": label_id,
                "confidence": confidence,
                "attrs": attrs,
            }
        )
        batch_items.append(
            irpb.DataItemIR(
                annotation=irpb.AnnotationRecord(
                    id=f"__prediction_{idx}__",
                    sample_id=f"__prediction_{idx}__",
                    label_id="__prediction__",
                    geometry=geometry,
                    source=irpb.ANNOTATION_SOURCE_MODEL,
                    confidence=confidence,
                )
            )
        )

    batch = irpb.DataBatchIR(items=batch_items)
    try:
        normalize_ir(batch)
    except IRError as exc:
        err_idx = _extract_error_index(exc)
        err_path = f"{path}[{err_idx}].geometry" if err_idx is not None else path
        raise _single_issue_error(
            code="IR_GEOMETRY_INVALID",
            path=err_path,
            message=exc.message,
            hint="geometry violates IR normalization rules",
        ) from exc

    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(parsed):
        payload = {
            "class_index": row["class_index"],
            "confidence": row["confidence"],
            "geometry": dict(
                MessageToDict(
                    batch.items[idx].annotation.geometry,
                    preserving_proto_field_name=True,
                )
            ),
        }
        if row["class_name"] is not None:
            payload["class_name"] = row["class_name"]
        if row["label_id"] is not None:
            payload["label_id"] = row["label_id"]
        if row["attrs"]:
            payload["attrs"] = row["attrs"]
        normalized.append(payload)
    return normalized


def normalize_prediction_entry(entry: dict[str, Any], *, path: str = "entry") -> dict[str, Any]:
    return _normalize_entries([entry], path=path)[0]


def normalize_prediction_snapshot(snapshot: dict[str, Any], *, path: str = "prediction_snapshot") -> dict[str, Any]:
    row = _require_mapping(snapshot, path=path, message=f"{path} must be an object")
    for key in row.keys():
        text = str(key)
        if text in _LEGACY_SNAPSHOT_FIELDS:
            raise _single_issue_error(
                code=IR_UNSUPPORTED_LEGACY_FIELD,
                path=f"{path}.{text}",
                message=f"legacy field '{text}' is not supported",
                hint="use prediction_snapshot.base_predictions or prediction_snapshot.predictions",
            )
        if text in _LEGACY_ENTRY_FIELDS:
            raise _single_issue_error(
                code=IR_UNSUPPORTED_LEGACY_FIELD,
                path=f"{path}.{text}",
                message=f"legacy field '{text}' is not supported",
            )

    normalized = dict(row)
    for field in ("base_predictions", "predictions"):
        if field not in row:
            continue
        value = row.get(field)
        if value is None:
            normalized[field] = []
            continue
        if not isinstance(value, list):
            raise _single_issue_error(
                code=IR_PREDICTION_FIELD_TYPE,
                path=f"{path}.{field}",
                message=f"{field} must be a list",
                value_preview=_preview(value),
            )
        normalized[field] = _normalize_entries([item for item in value], path=f"{path}.{field}")
    return normalized


def normalize_prediction_candidate(candidate: dict[str, Any], *, path: str = "candidate") -> dict[str, Any]:
    row = _require_mapping(candidate, path=path, message=f"{path} must be an object")
    if "predictionSnapshot" in row:
        raise _single_issue_error(
            code=IR_UNSUPPORTED_LEGACY_FIELD,
            path=f"{path}.predictionSnapshot",
            message="legacy field 'predictionSnapshot' is not supported",
            hint="use prediction_snapshot",
        )

    sample_id = str(row.get("sample_id") or "").strip()
    if not sample_id:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_MISSING,
            path=f"{path}.sample_id",
            message="sample_id is required",
        )
    score_raw = row.get("score")
    if score_raw is None:
        score = 0.0
    else:
        try:
            score = float(score_raw)
        except Exception as exc:
            raise _single_issue_error(
                code=IR_PREDICTION_FIELD_TYPE,
                path=f"{path}.score",
                message="score must be a number",
                value_preview=_preview(score_raw),
            ) from exc

    reason_raw = row.get("reason")
    if reason_raw is None:
        reason: dict[str, Any] = {}
    elif isinstance(reason_raw, Mapping):
        reason = dict(reason_raw)
    else:
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path=f"{path}.reason",
            message="reason must be an object",
            value_preview=_preview(reason_raw),
        )

    top_snapshot_raw = row.get("prediction_snapshot")
    reason_snapshot_raw = reason.get("prediction_snapshot")
    if isinstance(top_snapshot_raw, Mapping) and not dict(top_snapshot_raw):
        top_snapshot_raw = None
    if isinstance(reason_snapshot_raw, Mapping) and not dict(reason_snapshot_raw):
        reason_snapshot_raw = None
    normalized_top: dict[str, Any] | None = None
    normalized_reason: dict[str, Any] | None = None
    if top_snapshot_raw is not None:
        normalized_top = normalize_prediction_snapshot(
            _require_mapping(
                top_snapshot_raw,
                path=f"{path}.prediction_snapshot",
                message=f"{path}.prediction_snapshot must be an object",
            ),
            path=f"{path}.prediction_snapshot",
        )
    if reason_snapshot_raw is not None:
        normalized_reason = normalize_prediction_snapshot(
            _require_mapping(
                reason_snapshot_raw,
                path=f"{path}.reason.prediction_snapshot",
                message=f"{path}.reason.prediction_snapshot must be an object",
            ),
            path=f"{path}.reason.prediction_snapshot",
        )
    if normalized_top is not None and normalized_reason is not None and normalized_top != normalized_reason:
        raise _single_issue_error(
            code=IR_PREDICTION_CONFLICT,
            path=f"{path}.prediction_snapshot",
            message="prediction_snapshot conflicts with reason.prediction_snapshot",
            hint="ensure both snapshots are exactly the same object",
        )
    snapshot = normalized_top if normalized_top is not None else normalized_reason

    normalized = dict(row)
    normalized["sample_id"] = sample_id
    normalized["score"] = float(score)
    reason_out = dict(reason)
    if snapshot is not None:
        normalized["prediction_snapshot"] = snapshot
        reason_out["prediction_snapshot"] = snapshot
    normalized["reason"] = reason_out
    return normalized


def normalize_prediction_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        raise _single_issue_error(
            code=IR_PREDICTION_FIELD_TYPE,
            path="candidates",
            message="candidates must be a list",
            value_preview=_preview(candidates),
        )
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(candidates):
        normalized.append(normalize_prediction_candidate(row, path=f"candidate[{idx}]"))
    return normalized


__all__ = [
    "IR_PREDICTION_FIELD_MISSING",
    "IR_PREDICTION_FIELD_TYPE",
    "IR_PREDICTION_CONFLICT",
    "IR_UNSUPPORTED_LEGACY_FIELD",
    "normalize_prediction_entry",
    "normalize_prediction_snapshot",
    "normalize_prediction_candidate",
    "normalize_prediction_candidates",
]
