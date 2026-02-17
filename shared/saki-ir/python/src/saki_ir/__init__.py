from __future__ import annotations

from saki_ir.codec import decode_payload, encode_payload, iter_items, read_header
from saki_ir.dataframe import to_dataframe
from saki_ir.normalize import normalize_ir, validate_ir
from saki_ir.proto.saki.ir.v1.annotation_ir_pb2 import (  # noqa: F401
    AnnotationRecord,
    AnnotationSource,
    DataBatchIR,
    DataItemIR,
    EncodedPayload,
    Geometry,
    LabelRecord,
    ObbGeometry,
    PayloadChecksumAlgo,
    PayloadCodec,
    PayloadCompression,
    PayloadHeader,
    PayloadSchema,
    PayloadStats,
    RectGeometry,
    SampleRecord,
)

__all__ = [
    "normalize_ir",
    "validate_ir",
    "encode_payload",
    "decode_payload",
    "read_header",
    "iter_items",
    "to_dataframe",
    "DataBatchIR",
    "DataItemIR",
    "LabelRecord",
    "SampleRecord",
    "AnnotationRecord",
    "Geometry",
    "RectGeometry",
    "ObbGeometry",
    "AnnotationSource",
    "PayloadSchema",
    "PayloadCodec",
    "PayloadCompression",
    "PayloadChecksumAlgo",
    "PayloadStats",
    "PayloadHeader",
    "EncodedPayload",
]
