from __future__ import annotations

import pytest

from saki_plugin_sdk.prediction_types import normalize_prediction_candidates


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
    with pytest.raises(ValueError, match="sample_id"):
        normalize_prediction_candidates([{"score": 0.1}])


def test_normalize_candidates_rejects_missing_required_prediction_fields() -> None:
    with pytest.raises(ValueError, match="confidence"):
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


def test_normalize_candidates_rejects_invalid_geometry_by_ir_rules() -> None:
    with pytest.raises(ValueError, match="geometry is invalid"):
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
