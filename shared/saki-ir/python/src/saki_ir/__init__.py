from __future__ import annotations

from saki_ir.codec import decode_payload, decompress_raw, encode_payload, iter_items, read_header, verify_checksum
from saki_ir.dataframe import to_dataframe
from saki_ir.normalize import normalize_ir, validate_ir
from saki_ir.view import AnnotationView, BatchView, EncodedPayloadView, GeometryView, ObbView, RectView
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
    "decompress_raw",
    "verify_checksum",
    "read_header",
    "iter_items",
    "to_dataframe",
    "EncodedPayloadView",
    "BatchView",
    "AnnotationView",
    "GeometryView",
    "RectView",
    "ObbView",
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
