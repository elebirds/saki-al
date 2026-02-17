from __future__ import annotations

import pytest

import saki_ir.codec as codec_module
from saki_ir import BatchView, EncodedPayloadView, GeometryView, encode_payload
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


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


def test_view_header_only_no_zstd_needed_for_none() -> None:
    batch = _make_small_batch()
    encoded = encode_payload(batch, compression_threshold=1_000_000)
    assert encoded.header.compression == ir.PAYLOAD_COMPRESSION_NONE

    old_zstd = codec_module._zstd
    codec_module._zstd = None
    try:
        view = EncodedPayloadView(encoded)
        header = view.header
        stats = view.stats
        assert header.schema == ir.PAYLOAD_SCHEMA_DATA_BATCH_IR
        assert header.compression == ir.PAYLOAD_COMPRESSION_NONE
        assert stats.item_count == 3
    finally:
        codec_module._zstd = old_zstd


def test_view_verify_checksum_does_not_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("zstandard")

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
    encoded = encode_payload(ir.DataBatchIR(items=items))
    assert encoded.header.compression == ir.PAYLOAD_COMPRESSION_ZSTD

    calls = 0
    original = ir.DataBatchIR.ParseFromString

    def _spy(self, payload: bytes):
        nonlocal calls
        calls += 1
        return original(self, payload)

    monkeypatch.setattr(ir.DataBatchIR, "ParseFromString", _spy, raising=True)

    EncodedPayloadView(encoded).verify_checksum()
    assert calls == 0


def test_geometry_view_vertices_and_aabb() -> None:
    rect_geom = ir.Geometry(rect=ir.RectGeometry(x=10.0, y=20.0, width=100.0, height=40.0))
    rect_view = GeometryView(rect_geom)
    assert rect_view.vertices() == [(10.0, 20.0), (110.0, 20.0), (110.0, 60.0), (10.0, 60.0)]
    assert rect_view.aabb_rect_tl() == (10.0, 20.0, 100.0, 40.0)

    obb_geom = ir.Geometry(obb=ir.ObbGeometry(cx=100.0, cy=50.0, width=6.0, height=2.0, angle_deg_cw=30.0))
    obb_view = GeometryView(obb_geom)
    vertices = obb_view.vertices()
    x, y, w, h = obb_view.aabb_rect_tl()

    assert w > 0.0
    assert h > 0.0
    xs = [p[0] for p in vertices]
    ys = [p[1] for p in vertices]
    assert x == pytest.approx(min(xs), abs=1e-6)
    assert y == pytest.approx(min(ys), abs=1e-6)
    assert x + w == pytest.approx(max(xs), abs=1e-6)
    assert y + h == pytest.approx(max(ys), abs=1e-6)


def test_batch_view_normalized_copy_no_inplace() -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="ann-1",
                    sample_id="sample-1",
                    label_id="label-1",
                    confidence=0.8,
                    geometry=ir.Geometry(obb=ir.ObbGeometry(cx=10.0, cy=10.0, width=2.0, height=8.0, angle_deg_cw=15.0)),
                )
            )
        ]
    )
    view = BatchView(batch)
    copied = view.normalized_copy()

    src = batch.items[0].annotation.geometry.obb
    dst = copied.items[0].annotation.geometry.obb
    assert src.width == 2.0
    assert src.height == 8.0
    assert dst.width == pytest.approx(8.0, abs=1e-6)
    assert dst.height == pytest.approx(2.0, abs=1e-6)


def test_encoded_payload_view_decode_without_normalize() -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="ann-1",
                    sample_id="sample-1",
                    label_id="label-1",
                    confidence=0.8,
                    geometry=ir.Geometry(obb=ir.ObbGeometry(cx=10.0, cy=10.0, width=2.0, height=8.0, angle_deg_cw=15.0)),
                )
            )
        ]
    )
    encoded = encode_payload(batch, compression_threshold=1_000_000)
    view = EncodedPayloadView(encoded)

    decoded_raw = view.decode(normalize_output=False)
    raw_obb = decoded_raw.items[0].annotation.geometry.obb
    assert raw_obb.width == pytest.approx(2.0, abs=1e-6)
    assert raw_obb.height == pytest.approx(8.0, abs=1e-6)

    decoded_norm = view.decode(normalize_output=True)
    norm_obb = decoded_norm.items[0].annotation.geometry.obb
    assert norm_obb.width == pytest.approx(8.0, abs=1e-6)
    assert norm_obb.height == pytest.approx(2.0, abs=1e-6)
