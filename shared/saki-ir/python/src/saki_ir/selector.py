from __future__ import annotations

import hashlib
import struct

from saki_ir.errors import ERR_IR_SCHEMA, IRError
from saki_ir.proto.saki.ir.v1 import dataset_manifest_ir_pb2 as manifestirv1

_MAX_U32 = 2**32 - 1


def _normalize_ranges(selector: manifestirv1.RangeSelector) -> list[tuple[int, int]]:
    items: list[tuple[int, int]] = []
    for item in selector.ranges:
        start = int(item.start)
        end = int(item.end)
        if start < 0 or end < 0:
            raise IRError(ERR_IR_SCHEMA, "range ordinal must be non-negative")
        if end < start:
            raise IRError(ERR_IR_SCHEMA, "range end must be >= start")
        if start > _MAX_U32 or end > _MAX_U32:
            raise IRError(ERR_IR_SCHEMA, "range ordinal exceeds uint32")
        items.append((start, end))
    if not items:
        return []
    items.sort(key=lambda pair: (pair[0], pair[1]))
    merged: list[tuple[int, int]] = [items[0]]
    for start, end in items[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def selector_payload_bytes(selector: manifestirv1.ManifestSelector) -> bytes:
    if selector.encoding == manifestirv1.MANIFEST_SELECTOR_ENCODING_ROARING:
        if not selector.HasField("roaring"):
            raise IRError(ERR_IR_SCHEMA, "selector encoding roaring but payload missing")
        return bytes(selector.roaring.bitmap)
    if selector.encoding == manifestirv1.MANIFEST_SELECTOR_ENCODING_RANGE:
        if not selector.HasField("range"):
            raise IRError(ERR_IR_SCHEMA, "selector encoding range but payload missing")
        merged = _normalize_ranges(selector.range)
        chunks = [struct.pack("<II", start, end) for start, end in merged]
        return b"".join(chunks)
    if selector.encoding == manifestirv1.MANIFEST_SELECTOR_ENCODING_BITSET:
        if not selector.HasField("bitset"):
            raise IRError(ERR_IR_SCHEMA, "selector encoding bitset but payload missing")
        return bytes(selector.bitset.bitset_le)
    raise IRError(ERR_IR_SCHEMA, "selector encoding is unspecified")


def selector_cardinality(selector: manifestirv1.ManifestSelector) -> int:
    if selector.encoding == manifestirv1.MANIFEST_SELECTOR_ENCODING_ROARING:
        if int(selector.cardinality) > 0:
            return int(selector.cardinality)
        raise IRError(ERR_IR_SCHEMA, "roaring selector requires cardinality")
    if selector.encoding == manifestirv1.MANIFEST_SELECTOR_ENCODING_RANGE:
        merged = _normalize_ranges(selector.range)
        return int(sum((end - start + 1) for start, end in merged))
    if selector.encoding == manifestirv1.MANIFEST_SELECTOR_ENCODING_BITSET:
        return int(sum(int(byte).bit_count() for byte in selector.bitset.bitset_le))
    raise IRError(ERR_IR_SCHEMA, "selector encoding is unspecified")


def selector_checksum(selector: manifestirv1.ManifestSelector) -> str:
    if not selector.snapshot_id:
        raise IRError(ERR_IR_SCHEMA, "selector.snapshot_id is required")
    cardinality = selector_cardinality(selector)
    digest = hashlib.sha256()
    digest.update(selector.snapshot_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(struct.pack("<I", int(selector.encoding)))
    digest.update(selector_payload_bytes(selector))
    digest.update(struct.pack("<I", cardinality))
    return digest.hexdigest()


def validate_manifest_selector(selector: manifestirv1.ManifestSelector) -> tuple[int, str]:
    cardinality = selector_cardinality(selector)
    if int(selector.cardinality) > 0 and int(selector.cardinality) != cardinality:
        raise IRError(
            ERR_IR_SCHEMA,
            f"selector cardinality mismatch expected={int(selector.cardinality)} actual={cardinality}",
        )
    checksum = selector_checksum(selector)
    expected_checksum = str(selector.checksum or "").strip().lower()
    if expected_checksum and expected_checksum != checksum:
        raise IRError(
            ERR_IR_SCHEMA,
            f"selector checksum mismatch expected={expected_checksum} actual={checksum}",
        )
    return cardinality, checksum
