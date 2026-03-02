"""saki-ir Geometry ProtoJSON codec helpers.

This module is the single source of truth for annotation geometry/attrs normalization
inside saki-api. Storage contract:
- `Annotation.geometry` stores `saki_ir Geometry` ProtoJSON (preserving proto field names)
- `Annotation.attrs` stores free-form JSON object
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict

from saki_ir import normalize_ir
from saki_ir.errors import IRError
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

    if not isinstance(payload, Mapping):
        raise BadRequestAppException("geometry must be an object")

    geometry = irpb.Geometry()
    try:
        ParseDict(dict(payload), geometry, ignore_unknown_fields=False)
    except Exception as exc:  # pragma: no cover - protobuf parse details vary by runtime
        raise BadRequestAppException(f"Invalid geometry payload: {exc}") from exc

    shape = geometry.WhichOneof("shape")
    if shape not in _SHAPE_TO_TYPE:
        raise BadRequestAppException("geometry.shape is required and must be rect or obb")

    return geometry


def geometry_to_dict(geometry: irpb.Geometry) -> dict[str, Any]:
    """Convert protobuf Geometry message to ProtoJSON dict (snake_case)."""

    return dict(MessageToDict(geometry, preserving_proto_field_name=True))


def infer_annotation_type_from_geometry(geometry: irpb.Geometry) -> AnnotationType:
    """Infer annotation type from Geometry oneof shape."""

    shape = geometry.WhichOneof("shape")
    ann_type = _SHAPE_TO_TYPE.get(str(shape))
    if ann_type is None:
        raise BadRequestAppException("geometry.shape is required and must be rect or obb")
    return ann_type


def _annotation_source_to_ir(source: AnnotationSource) -> irpb.AnnotationSource:
    if source == AnnotationSource.MANUAL:
        return irpb.ANNOTATION_SOURCE_MANUAL
    if source == AnnotationSource.MODEL:
        return irpb.ANNOTATION_SOURCE_MODEL
    if source == AnnotationSource.CONFIRMED_MODEL:
        return irpb.ANNOTATION_SOURCE_CONFIRMED_MODEL
    if source == AnnotationSource.SYSTEM:
        return irpb.ANNOTATION_SOURCE_SYSTEM
    if source == AnnotationSource.IMPORTED:
        return irpb.ANNOTATION_SOURCE_IMPORTED
    return irpb.ANNOTATION_SOURCE_UNSPECIFIED


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
    ann_source = normalize_annotation_source(source)
    geometry = parse_geometry_dict(geometry_payload)

    expected_shape = _TYPE_TO_SHAPE[ann_type]
    actual_shape = geometry.WhichOneof("shape")
    if actual_shape != expected_shape:
        raise BadRequestAppException(
            f"type/geometry mismatch: type={ann_type.value} requires geometry.{expected_shape}, got geometry.{actual_shape}"
        )

    batch = irpb.DataBatchIR(
        items=[
            irpb.DataItemIR(
                annotation=irpb.AnnotationRecord(
                    id="__validation__",
                    sample_id="__validation__",
                    label_id="__validation__",
                    geometry=geometry,
                    source=_annotation_source_to_ir(ann_source),
                    confidence=float(confidence),
                )
            )
        ]
    )
    try:
        normalize_ir(batch)
    except IRError as exc:
        raise BadRequestAppException(exc.message) from exc

    normalized_geometry = batch.items[0].annotation.geometry
    return ann_type, geometry_to_dict(normalized_geometry)


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
