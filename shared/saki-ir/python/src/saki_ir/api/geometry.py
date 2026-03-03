from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from google.protobuf.json_format import MessageToDict, ParseDict

from saki_ir.errors import IRError
from saki_ir.normalize import normalize_ir
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb

from .errors import IRValidationError, IRValidationIssue

IR_GEOMETRY_INVALID = "IR_GEOMETRY_INVALID"


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


def _preview(value: Any) -> str:
    try:
        text = repr(value)
    except Exception:
        text = "<unreprable>"
    if len(text) <= 160:
        return text
    return text[:157] + "..."


def parse_geometry(payload: dict[str, Any]) -> irpb.Geometry:
    return _parse_geometry(payload, path="geometry")


def _parse_geometry(payload: Any, *, path: str) -> irpb.Geometry:
    if not isinstance(payload, Mapping):
        raise _single_issue_error(
            code=IR_GEOMETRY_INVALID,
            path=path,
            message="geometry must be an object",
            hint="provide {'rect': {...}} or {'obb': {...}}",
            value_preview=_preview(payload),
        )
    geometry = irpb.Geometry()
    try:
        ParseDict(dict(payload), geometry, ignore_unknown_fields=False)
    except Exception as exc:  # pragma: no cover
        raise _single_issue_error(
            code=IR_GEOMETRY_INVALID,
            path=path,
            message=f"invalid geometry payload: {exc}",
            hint="check field names and numeric types",
            value_preview=_preview(payload),
        ) from exc

    shape = geometry.WhichOneof("shape")
    if shape not in {"rect", "obb"}:
        raise _single_issue_error(
            code=IR_GEOMETRY_INVALID,
            path=f"{path}.shape",
            message="geometry.shape is required and must be rect or obb",
            hint="set either geometry.rect or geometry.obb",
            value_preview=_preview(payload),
        )
    return geometry


def geometry_proto_to_payload(geometry: irpb.Geometry) -> dict[str, Any]:
    if not isinstance(geometry, irpb.Geometry):
        raise _single_issue_error(
            code=IR_GEOMETRY_INVALID,
            path="geometry",
            message="geometry proto is required",
            hint="pass saki_ir.proto...Geometry instance",
            value_preview=_preview(geometry),
        )
    return dict(MessageToDict(geometry, preserving_proto_field_name=True))


def infer_shape(payload_or_proto: Any) -> Literal["rect", "obb"]:
    if isinstance(payload_or_proto, irpb.Geometry):
        shape = payload_or_proto.WhichOneof("shape")
    else:
        geometry = _parse_geometry(payload_or_proto, path="geometry")
        shape = geometry.WhichOneof("shape")
    if shape == "rect":
        return "rect"
    if shape == "obb":
        return "obb"
    raise _single_issue_error(
        code=IR_GEOMETRY_INVALID,
        path="geometry.shape",
        message="geometry.shape is required and must be rect or obb",
    )


def _normalize_geometry_proto(geometry: irpb.Geometry, *, path: str) -> irpb.Geometry:
    batch = irpb.DataBatchIR(
        items=[
            irpb.DataItemIR(
                annotation=irpb.AnnotationRecord(
                    id="__geometry_validation__",
                    sample_id="__geometry_validation__",
                    label_id="__geometry_validation__",
                    geometry=geometry,
                    source=irpb.ANNOTATION_SOURCE_MODEL,
                    confidence=1.0,
                )
            )
        ]
    )
    try:
        normalize_ir(batch)
    except IRError as exc:
        raise _single_issue_error(
            code=IR_GEOMETRY_INVALID,
            path=path,
            message=exc.message,
            hint="geometry violates IR normalization rules",
            value_preview=_preview(geometry_proto_to_payload(geometry)),
        ) from exc
    return batch.items[0].annotation.geometry


def normalize_geometry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    geometry = _parse_geometry(payload, path="geometry")
    normalized = _normalize_geometry_proto(geometry, path="geometry")
    return geometry_proto_to_payload(normalized)


def validate_geometry_payload(payload: dict[str, Any]) -> None:
    geometry = _parse_geometry(payload, path="geometry")
    _normalize_geometry_proto(geometry, path="geometry")


__all__ = [
    "IR_GEOMETRY_INVALID",
    "parse_geometry",
    "normalize_geometry_payload",
    "validate_geometry_payload",
    "geometry_proto_to_payload",
    "infer_shape",
]
