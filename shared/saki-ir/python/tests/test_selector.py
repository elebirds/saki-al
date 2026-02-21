from __future__ import annotations

import json
from pathlib import Path

import pytest

from saki_ir.errors import IRError
from saki_ir.proto.saki.ir.v1 import dataset_manifest_ir_pb2 as manifestirv1
from saki_ir.selector import selector_cardinality, selector_checksum, validate_manifest_selector


def _vector_cases() -> list[dict]:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "testdata" / "selector_vector.json").read_text(encoding="utf-8"))
    return list(payload.get("cases", []))


def _build_selector(case: dict) -> manifestirv1.ManifestSelector:
    encoding = str(case.get("encoding") or "").strip().upper()
    selector = manifestirv1.ManifestSelector(snapshot_id=str(case.get("snapshot_id") or ""))
    if encoding == "RANGE":
        selector.encoding = manifestirv1.MANIFEST_SELECTOR_ENCODING_RANGE
        for start, end in case.get("ranges", []):
            selector.range.ranges.add(start=int(start), end=int(end))
    elif encoding == "BITSET":
        selector.encoding = manifestirv1.MANIFEST_SELECTOR_ENCODING_BITSET
        selector.bitset.bitset_le = bytes.fromhex(str(case.get("bitset_le_hex") or ""))
    elif encoding == "ROARING":
        selector.encoding = manifestirv1.MANIFEST_SELECTOR_ENCODING_ROARING
        selector.roaring.bitmap = bytes.fromhex(str(case.get("roaring_hex") or ""))
    else:
        raise ValueError(f"unsupported encoding: {encoding}")
    selector.cardinality = int(case.get("cardinality") or 0)
    selector.checksum = str(case.get("checksum") or "")
    return selector


def test_selector_vector_cardinality_and_checksum() -> None:
    for case in _vector_cases():
        selector = _build_selector(case)
        assert selector_cardinality(selector) == int(case["cardinality"]), case["name"]
        assert selector_checksum(selector) == str(case["checksum"]), case["name"]
        cardinality, checksum = validate_manifest_selector(selector)
        assert cardinality == int(case["cardinality"]), case["name"]
        assert checksum == str(case["checksum"]), case["name"]


def test_selector_validation_detects_checksum_mismatch() -> None:
    case = _vector_cases()[0]
    selector = _build_selector(case)
    selector.checksum = "deadbeef"
    with pytest.raises(IRError):
        validate_manifest_selector(selector)
