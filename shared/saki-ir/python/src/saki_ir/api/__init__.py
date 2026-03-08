from saki_ir.api.errors import IRValidationError, IRValidationIssue
from saki_ir.api.geometry import (
    IR_GEOMETRY_INVALID,
    geometry_proto_to_payload,
    infer_shape,
    normalize_geometry_payload,
    parse_geometry,
    validate_geometry_payload,
)
from saki_ir.api.prediction import (
    IR_PREDICTION_CONFLICT,
    IR_PREDICTION_FIELD_MISSING,
    IR_PREDICTION_FIELD_TYPE,
    IR_UNSUPPORTED_LEGACY_FIELD,
    normalize_prediction_candidate,
    normalize_prediction_candidates,
    normalize_prediction_entry,
    normalize_prediction_snapshot,
)
from saki_ir.quad8 import (
    flip_quad8,
    geometry_to_quad8_local,
    normalize_quad8,
    quad8_to_aabb_rect,
    quad8_to_obb_payload,
)

__all__ = [
    "IRValidationIssue",
    "IRValidationError",
    "IR_GEOMETRY_INVALID",
    "IR_PREDICTION_FIELD_MISSING",
    "IR_PREDICTION_FIELD_TYPE",
    "IR_PREDICTION_CONFLICT",
    "IR_UNSUPPORTED_LEGACY_FIELD",
    "parse_geometry",
    "normalize_geometry_payload",
    "validate_geometry_payload",
    "geometry_proto_to_payload",
    "infer_shape",
    "normalize_quad8",
    "geometry_to_quad8_local",
    "quad8_to_aabb_rect",
    "flip_quad8",
    "quad8_to_obb_payload",
    "normalize_prediction_entry",
    "normalize_prediction_snapshot",
    "normalize_prediction_candidate",
    "normalize_prediction_candidates",
]
