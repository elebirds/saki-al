from __future__ import annotations

import pytest

from saki_ir import IRValidationError, normalize_prediction_candidates, normalize_prediction_entry


def _prediction_entry() -> dict:
    return {
        "class_index": 1,
        "class_name": "car",
        "confidence": 0.9,
        "geometry": {
            "rect": {
                "x": 10,
                "y": 12,
                "width": 20,
                "height": 30,
            }
        },
        "attrs": {"source": "test"},
    }


def test_normalize_prediction_entry_success() -> None:
    row = normalize_prediction_entry(_prediction_entry())
    assert row["class_index"] == 1
    assert row["class_name"] == "car"
    assert row["confidence"] == pytest.approx(0.9)
    assert "rect" in row["geometry"]


def test_normalize_prediction_candidates_success() -> None:
    rows = normalize_prediction_candidates(
        [
            {
                "sample_id": "sample-1",
                "score": 0.42,
                "reason": {
                    "prediction_snapshot": {
                        "base_predictions": [_prediction_entry()],
                    }
                },
            }
        ]
    )
    snapshot = rows[0]["reason"]["prediction_snapshot"]
    assert isinstance(snapshot.get("base_predictions"), list)
    assert snapshot["base_predictions"][0]["class_index"] == 1


def test_prediction_conflict_between_top_and_reason_snapshot_fails() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_prediction_candidates(
            [
                {
                    "sample_id": "sample-1",
                    "score": 0.7,
                    "prediction_snapshot": {
                        "base_predictions": [{**_prediction_entry(), "class_index": 0}],
                    },
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [{**_prediction_entry(), "class_index": 1}],
                        }
                    },
                }
            ]
        )
    first = exc_info.value.issues[0]
    assert first.code == "IR_PREDICTION_CONFLICT"
    assert first.path == "candidate[0].prediction_snapshot"


def test_prediction_legacy_field_rejected() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_prediction_candidates(
            [
                {
                    "sample_id": "sample-1",
                    "score": 0.7,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "cls_id": 1,
                                    "conf": 0.8,
                                    "xyxy": [1, 2, 3, 4],
                                }
                            ]
                        }
                    },
                }
            ]
        )
    first = exc_info.value.issues[0]
    assert first.code == "IR_UNSUPPORTED_LEGACY_FIELD"
    assert "cls_id" in first.path


def test_prediction_invalid_geometry_reports_path() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_prediction_candidates(
            [
                {
                    "sample_id": "sample-1",
                    "score": 0.7,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 1,
                                    "confidence": 0.8,
                                    "geometry": {"rect": {"x": 0, "y": 0, "width": -1, "height": 3}},
                                }
                            ]
                        }
                    },
                }
            ]
        )
    first = exc_info.value.issues[0]
    assert first.code == "IR_GEOMETRY_INVALID"
    assert first.path == "candidate[0].reason.prediction_snapshot.base_predictions[0].geometry"
