"""saki-ir Geometry ProtoJSON codec helpers.

This module is the single source of truth for annotation geometry/attrs normalization
inside saki-api. Storage contract:
- `Annotation.geometry` stores `saki_ir Geometry` ProtoJSON (preserving proto field names)
- `Annotation.attrs` stores free-form JSON object
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saki_ir import (
    IRValidationError,
    geometry_proto_to_payload,
    infer_shape,
    normalize_geometry_payload as ir_normalize_geometry_payload,
    parse_geometry,
)
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.shared.modeling.enums import AnnotationSource, AnnotationType

_SUPPORTED_TYPES: tuple[AnnotationType, ...] = (AnnotationType.RECT, AnnotationType.OBB)
_TYPE_TO_SHAPE: dict[AnnotationType, str] = {
    AnnotationType.RECT: "rect",
    AnnotationType.OBB: "obb",
}
_SHAPE_TO_TYPE: dict[str, AnnotationType] = {
    "rect": AnnotationType.RECT,
    "obb": AnnotationType.OBB,
}


def normalize_annotation_type(value: Any, *, default: AnnotationType = AnnotationType.RECT) -> AnnotationType:
    """Normalize annotation type and enforce v1-supported shapes (rect/obb only)."""

    if value is None:
        ann_type = default
    elif isinstance(value, AnnotationType):
        ann_type = value
    else:
        try:
            ann_type = AnnotationType(str(value).strip().lower())
        except ValueError as exc:
            raise BadRequestAppException(f"Unsupported annotation type: {value}") from exc

    if ann_type not in _SUPPORTED_TYPES:
        raise BadRequestAppException(
            f"Unsupported annotation type in v1: {ann_type.value}. Only rect/obb are allowed"
        )
    return ann_type


def normalize_annotation_source(value: Any, *, default: AnnotationSource = AnnotationSource.MANUAL) -> AnnotationSource:
    """Normalize annotation source enum value."""

    if value is None:
        return default
    if isinstance(value, AnnotationSource):
        return value
    try:
        return AnnotationSource(str(value).strip().lower())
    except ValueError as exc:
        raise BadRequestAppException(f"Unsupported annotation source: {value}") from exc


def normalize_attrs(attrs: Any) -> dict[str, Any]:
    """Normalize attrs payload.

    Non-object inputs are normalized to empty object by contract.
    """

    if isinstance(attrs, Mapping):
        return dict(attrs)
    return {}


def parse_geometry_dict(payload: Any) -> irpb.Geometry:
    """Parse Geometry ProtoJSON dict into protobuf message."""
    try:
        mapping = dict(payload) if isinstance(payload, Mapping) else payload
        return parse_geometry(mapping)
    except IRValidationError as exc:
        issue = exc.issues[0]
        raise BadRequestAppException(f"[{issue.code}] {issue.message} (path={issue.path}, phase=geometry)") from exc


def geometry_to_dict(geometry: irpb.Geometry) -> dict[str, Any]:
    """Convert protobuf Geometry message to ProtoJSON dict (snake_case)."""
    try:
        return geometry_proto_to_payload(geometry)
    except IRValidationError as exc:
        issue = exc.issues[0]
        raise BadRequestAppException(f"[{issue.code}] {issue.message} (path={issue.path}, phase=geometry)") from exc


def infer_annotation_type_from_geometry(geometry: irpb.Geometry) -> AnnotationType:
    """Infer annotation type from Geometry oneof shape."""
    try:
        shape = infer_shape(geometry)
    except IRValidationError as exc:
        issue = exc.issues[0]
        raise BadRequestAppException(f"[{issue.code}] {issue.message} (path={issue.path}, phase=geometry)") from exc
    ann_type = _SHAPE_TO_TYPE.get(str(shape))
    if ann_type is None:
        raise BadRequestAppException("geometry.shape is required and must be rect or obb")
    return ann_type


def normalize_geometry_payload(
    *,
    annotation_type: Any,
    geometry_payload: Any,
    confidence: float = 1.0,
    source: Any = AnnotationSource.MANUAL,
) -> tuple[AnnotationType, dict[str, Any]]:
    """Validate and normalize geometry using saki-ir semantics.

    Returns:
        `(normalized_annotation_type, normalized_geometry_protojson)`
    """

    ann_type = normalize_annotation_type(annotation_type)
    normalize_annotation_source(source)

    try:
        confidence_value = float(confidence)
    except Exception as exc:
        raise BadRequestAppException("confidence must be a valid number") from exc
    if confidence_value < 0.0 or confidence_value > 1.0:
        raise BadRequestAppException("confidence must be in range [0, 1]")

    if not isinstance(geometry_payload, Mapping):
        raise BadRequestAppException("geometry must be an object")
    try:
        normalized_geometry = ir_normalize_geometry_payload(dict(geometry_payload))
    except IRValidationError as exc:
        issue = exc.issues[0]
        raise BadRequestAppException(f"[{issue.code}] {issue.message} (path={issue.path}, phase=geometry)") from exc

    expected_shape = _TYPE_TO_SHAPE[ann_type]
    actual_shape = str(infer_shape(normalized_geometry))
    if actual_shape != expected_shape:
        raise BadRequestAppException(
            f"type/geometry mismatch: type={ann_type.value} requires geometry.{expected_shape}, got geometry.{actual_shape}"
        )
    return ann_type, normalized_geometry


def normalize_annotation_payload(
    *,
    annotation_type: Any,
    geometry_payload: Any,
    attrs_payload: Any,
    confidence: float = 1.0,
    source: Any = AnnotationSource.MANUAL,
) -> tuple[AnnotationType, dict[str, Any], dict[str, Any]]:
    """Normalize type/geometry/attrs triplet for annotation persistence."""

    ann_type, geometry = normalize_geometry_payload(
        annotation_type=annotation_type,
        geometry_payload=geometry_payload,
        confidence=confidence,
        source=source,
    )
    attrs = normalize_attrs(attrs_payload)
    return ann_type, geometry, attrs
