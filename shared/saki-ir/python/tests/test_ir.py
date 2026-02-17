from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saki_ir import decode_payload, encode_payload, normalize_ir, read_header, to_dataframe, validate_ir
from saki_ir.codec import checksum_crc32c
from saki_ir.errors import (
    ERR_IR_CHECKSUM_MISMATCH,
    ERR_IR_GEOMETRY,
    ERR_IR_SCHEMA,
    IRError,
)
from saki_ir.geom import obb_to_vertices
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def _make_obb_annotation(width: float, height: float, angle: float, confidence: float = 0.5) -> ir.DataBatchIR:
    return ir.DataBatchIR(
        items=[
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="ann-1",
                    sample_id="sample-1",
                    label_id="label-1",
                    confidence=confidence,
                    geometry=ir.Geometry(
                        obb=ir.ObbGeometry(cx=100.0, cy=50.0, width=width, height=height, angle_deg_cw=angle)
                    ),
                )
            )
        ]
    )


def _make_rect_annotation(x: float, y: float, w: float, h: float, confidence: float = 0.5) -> ir.DataBatchIR:
    return ir.DataBatchIR(
        items=[
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="ann-r",
                    sample_id="sample-1",
                    label_id="label-1",
                    confidence=confidence,
                    geometry=ir.Geometry(rect=ir.RectGeometry(x=x, y=y, width=w, height=h)),
                )
            )
        ]
    )


def _make_small_batch() -> ir.DataBatchIR:
    return ir.DataBatchIR(
        items=[
            ir.DataItemIR(label=ir.LabelRecord(id="label-1", name="car", color="#ff0000")),
            ir.DataItemIR(sample=ir.SampleRecord(id="sample-1", asset_hash="hash-1", width=1920, height=1080)),
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="ann-1",
                    sample_id="sample-1",
                    label_id="label-1",
                    source=ir.ANNOTATION_SOURCE_MANUAL,
                    confidence=0.9,
                    geometry=ir.Geometry(rect=ir.RectGeometry(x=10.0, y=20.0, width=100.0, height=40.0)),
                )
            ),
        ]
    )


def test_obb_normalize_golden_cases() -> None:
    cases = [
        (4.0, 2.0, 0.0, 4.0, 2.0, 0.0),
        (2.0, 4.0, 0.0, 4.0, 2.0, 90.0),
        (1.0, 5.0, 100.0, 5.0, 1.0, -170.0),
        (3.0, 6.0, 179.0, 6.0, 3.0, -91.0),
        (5.0, 3.0, 180.0, 5.0, 3.0, -180.0),
        (5.0, 3.0, -181.0, 5.0, 3.0, 179.0),
        (2.0, 8.0, -181.0, 8.0, 2.0, -91.0),
        (2.0, 8.0, 270.0, 8.0, 2.0, 0.0),
    ]

    for width, height, angle, exp_w, exp_h, exp_angle in cases:
        batch = _make_obb_annotation(width, height, angle)
        normalize_ir(batch)
        obb = batch.items[0].annotation.geometry.obb
        assert obb.width == pytest.approx(exp_w, abs=1e-6)
        assert obb.height == pytest.approx(exp_h, abs=1e-6)
        assert obb.angle_deg_cw == pytest.approx(exp_angle, abs=1e-6)


def test_rect_invalid_cases() -> None:
    cases = [
        _make_rect_annotation(0.0, 0.0, 0.0, 10.0),
        _make_rect_annotation(0.0, 0.0, 10.0, -1.0),
        _make_rect_annotation(float("nan"), 0.0, 10.0, 10.0),
        _make_rect_annotation(0.0, float("inf"), 10.0, 10.0),
    ]

    for batch in cases:
        with pytest.raises(IRError) as exc:
            validate_ir(batch)
        assert exc.value.code == ERR_IR_GEOMETRY


def test_confidence_invalid() -> None:
    for confidence in (-0.1, 1.1, float("nan"), float("inf")):
        batch = _make_obb_annotation(4.0, 2.0, 0.0, confidence=confidence)
        with pytest.raises(IRError) as exc:
            validate_ir(batch)
        assert exc.value.code == ERR_IR_SCHEMA


def test_encode_decode_roundtrip_none() -> None:
    batch = _make_small_batch()
    encoded = encode_payload(batch, compression_threshold=1_000_000)

    assert encoded.header.compression == ir.PAYLOAD_COMPRESSION_NONE

    decoded = decode_payload(encoded)
    expected = ir.DataBatchIR()
    expected.ParseFromString(batch.SerializeToString())
    normalize_ir(expected)

    assert decoded.SerializeToString() == expected.SerializeToString()


def test_encode_decode_roundtrip_zstd() -> None:
    items = [ir.DataItemIR(label=ir.LabelRecord(id="label-1", name="car", color="#ff0000"))]
    for i in range(5000):
        items.append(
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id=f"ann-{i}",
                    sample_id="sample-1",
                    label_id="label-1",
                    source=ir.ANNOTATION_SOURCE_MODEL,
                    confidence=0.7,
                    geometry=ir.Geometry(rect=ir.RectGeometry(x=float(i), y=1.0, width=100.0, height=30.0)),
                )
            )
        )
    batch = ir.DataBatchIR(items=items)

    encoded = encode_payload(batch)
    assert encoded.header.compression == ir.PAYLOAD_COMPRESSION_ZSTD

    decoded = decode_payload(encoded)
    assert len(decoded.items) == len(batch.items)


def test_encode_parameter_normalization_and_bounds() -> None:
    batch = _make_small_batch()

    encoded = encode_payload(batch, compression_threshold=-1, zstd_level=0)
    assert encoded.header.compression == ir.PAYLOAD_COMPRESSION_ZSTD

    with pytest.raises(IRError) as exc:
        encode_payload(batch, zstd_level=23)
    assert exc.value.code == ERR_IR_SCHEMA

    with pytest.raises(IRError) as exc:
        encode_payload(batch, zstd_level=-1)
    assert exc.value.code == ERR_IR_SCHEMA


def test_checksum_mismatch() -> None:
    batch = _make_small_batch()
    encoded = encode_payload(batch, compression_threshold=1_000_000)
    encoded.header.checksum = (encoded.header.checksum + 1) & 0xFFFFFFFF

    with pytest.raises(IRError) as exc:
        decode_payload(encoded)
    assert exc.value.code == ERR_IR_CHECKSUM_MISMATCH


def test_read_header_without_zstd_dependency_on_none() -> None:
    import saki_ir.codec as codec_module

    batch = _make_small_batch()
    encoded = encode_payload(batch, compression_threshold=1_000_000)
    assert encoded.header.compression == ir.PAYLOAD_COMPRESSION_NONE

    old_zstd = codec_module._zstd
    codec_module._zstd = None
    try:
        header = read_header(encoded)
        assert header.schema == ir.PAYLOAD_SCHEMA_DATA_BATCH_IR
        assert header.compression == ir.PAYLOAD_COMPRESSION_NONE
    finally:
        codec_module._zstd = old_zstd


def test_crc32c_standard_vector() -> None:
    assert checksum_crc32c(b"123456789") == 0xE3069283


def test_cross_language_crc32c_vector() -> None:
    vector_file = Path(__file__).resolve().parents[2] / "testdata" / "crc32c_vector.json"
    data = json.loads(vector_file.read_text(encoding="utf-8"))
    payload_raw = bytes.fromhex(data["payload_raw_hex"])
    expected = int(data["expected_crc32c"])
    assert checksum_crc32c(payload_raw) == expected


def test_to_dataframe_annotation_schema() -> None:
    pd = pytest.importorskip("pandas")

    batch = _make_small_batch()
    df = to_dataframe(batch, kind="annotation")
    assert isinstance(df, pd.DataFrame)
    assert set(
        [
            "id",
            "sample_id",
            "label_id",
            "source",
            "confidence",
            "shape",
            "rect_x",
            "rect_y",
            "rect_w",
            "rect_h",
            "obb_cx",
            "obb_cy",
            "obb_w",
            "obb_h",
            "obb_angle_deg_cw",
        ]
    ).issubset(df.columns)
    assert len(df) == 1


def test_normalize_angle_range() -> None:
    batch = _make_obb_annotation(4.0, 2.0, -540.0)
    normalize_ir(batch)
    angle = batch.items[0].annotation.geometry.obb.angle_deg_cw
    assert -180.0 <= angle < 180.0
    assert math.isfinite(angle)


def test_obb_vertices_invariant_after_normalize() -> None:
    batch = _make_obb_annotation(2.0, 8.0, 35.0)
    before = obb_to_vertices(batch.items[0].annotation.geometry.obb)
    normalize_ir(batch)
    after = obb_to_vertices(batch.items[0].annotation.geometry.obb)

    def _sorted(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return sorted((round(x, 4), round(y, 4)) for x, y in points)

    assert _sorted(before) == _sorted(after)


def test_obb_vertices_direction_zero_angle() -> None:
    obb = ir.ObbGeometry(cx=10.0, cy=10.0, width=6.0, height=2.0, angle_deg_cw=0.0)
    tl, tr, br, _ = obb_to_vertices(obb)
    assert tr[0] > tl[0]
    assert tr[1] == pytest.approx(tl[1], abs=1e-6)
    assert br[1] > tr[1]
