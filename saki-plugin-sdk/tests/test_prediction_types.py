from __future__ import annotations

import pytest

from saki_ir import IRValidationError
from saki_plugin_sdk import normalize_prediction_candidates


def test_normalize_candidates_accepts_v3_prediction_snapshot() -> None:
    rows = normalize_prediction_candidates(
        [
            {
                "sample_id": "s1",
                "score": 0.8,
                "reason": {
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 1,
                                "class_name": "car",
                                "confidence": 0.9,
                                "geometry": {
                                    "rect": {"x": 1, "y": 2, "width": 2, "height": 2},
                                },
                            }
                        ]
                    }
                },
            }
        ]
    )
    pred = rows[0]["reason"]["prediction_snapshot"]["base_predictions"][0]
    assert pred["class_index"] == 1
    assert pred["class_name"] == "car"
    assert pred["confidence"] == pytest.approx(0.9)


def test_normalize_candidates_requires_sample_id() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_prediction_candidates([{"score": 0.1}])
    first = exc_info.value.issues[0]
    assert first.code == "IR_PREDICTION_FIELD_MISSING"
    assert first.path == "candidate[0].sample_id"


def test_normalize_candidates_rejects_missing_required_prediction_fields() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_prediction_candidates(
            [
                {
                    "sample_id": "s1",
                    "score": 0.1,
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "geometry": {"rect": {"x": 0, "y": 0, "width": 1, "height": 1}},
                            }
                        ]
                    },
                }
            ]
        )
    first = exc_info.value.issues[0]
    assert first.code == "IR_PREDICTION_FIELD_MISSING"
    assert "confidence" in first.path


def test_normalize_candidates_rejects_invalid_geometry_by_ir_rules() -> None:
    with pytest.raises(IRValidationError) as exc_info:
        normalize_prediction_candidates(
            [
                {
                    "sample_id": "s1",
                    "score": 0.1,
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "confidence": 0.8,
                                "geometry": {"rect": {"x": 0, "y": 0, "width": -1, "height": 2}},
                            }
                        ]
                    },
                }
            ]
        )
    first = exc_info.value.issues[0]
    assert first.code == "IR_GEOMETRY_INVALID"
    assert "geometry" in first.path
