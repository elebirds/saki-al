from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from saki_plugin_yolo_det.predict_pipeline import _stable_random_score, score_unlabeled_samples


def test_stable_random_score_is_deterministic() -> None:
    first = _stable_random_score(sample_id="sample-a", random_seed=11)
    second = _stable_random_score(sample_id="sample-a", random_seed=11)
    third = _stable_random_score(sample_id="sample-b", random_seed=11)
    assert first == second
    assert first != third


def test_random_baseline_candidates_are_round_invariant(tmp_path: Path) -> None:
    sample_a = tmp_path / "a.jpg"
    sample_b = tmp_path / "b.jpg"
    sample_a.write_bytes(b"\x00")
    sample_b.write_bytes(b"\x00")
    unlabeled_samples = [
        {"id": "sample-a", "local_path": str(sample_a)},
        {"id": "sample-b", "local_path": str(sample_b)},
    ]

    kwargs = {
        "unlabeled_samples": unlabeled_samples,
        "strategy": "random_baseline",
        "conf": 0.25,
        "imgsz": 640,
        "device": "cpu",
        "stop_flag": Event(),
        "get_model": None,
        "predict_single_image": lambda **_kw: [],
        "predict_with_aug": lambda **_kw: [],
        "extract_predictions": lambda _pred: [],
        "build_detection_boxes": lambda _rows: [],
        "score_aug_iou_disagreement": lambda _rows: (0.0, {}),
        "score_by_strategy": lambda *args, **kwargs: (0.0, {"args": args, "kwargs": kwargs}),
        "normalize_strategy_name": lambda name: str(name).strip().lower(),
        "random_seed": 7,
    }
    round_1 = score_unlabeled_samples(round_index=1, **kwargs)
    round_9 = score_unlabeled_samples(round_index=9, **kwargs)

    score_1 = {row["sample_id"]: float(row["score"]) for row in round_1}
    score_9 = {row["sample_id"]: float(row["score"]) for row in round_9}
    assert score_1 == score_9
    assert all("round_index" not in (row.get("reason") or {}) for row in round_1)


def test_aug_iou_strategy_passes_qbox_rows_to_build_boxes(tmp_path: Path) -> None:
    sample = tmp_path / "a.jpg"
    sample.write_bytes(b"\x00")
    unlabeled_samples = [{"id": "sample-a", "local_path": str(sample)}]

    seen_rows: list[list[dict]] = []

    def _predict_with_aug(**_kw):
        return [
            [
                {
                    "class_index": 0,
                    "confidence": 0.9,
                    "qbox": (0.0, 0.0, 4.0, 0.0, 4.0, 2.0, 0.0, 2.0),
                    "geometry": {"rect": {"x": 0.0, "y": 0.0, "width": 4.0, "height": 2.0}},
                }
            ],
            [
                {
                    "class_index": 0,
                    "confidence": 0.8,
                    "qbox": (0.2, 0.0, 4.2, 0.0, 4.2, 2.0, 0.2, 2.0),
                    "geometry": {"rect": {"x": 0.2, "y": 0.0, "width": 4.0, "height": 2.0}},
                }
            ],
        ]

    def _build_detection_boxes(rows):
        seen_rows.append(rows)
        return rows

    def _score_aug_iou(rows_by_aug):
        assert rows_by_aug[0][0]["qbox"] == (0.0, 0.0, 4.0, 0.0, 4.0, 2.0, 0.0, 2.0)
        assert rows_by_aug[1][0]["qbox"] == (0.2, 0.0, 4.2, 0.0, 4.2, 2.0, 0.2, 2.0)
        return 0.42, {"score": 0.42}

    rows = score_unlabeled_samples(
        unlabeled_samples=unlabeled_samples,
        strategy="aug_iou_disagreement",
        conf=0.25,
        imgsz=640,
        device="cpu",
        stop_flag=Event(),
        get_model=lambda: object(),
        predict_single_image=lambda **_kw: [],
        predict_with_aug=_predict_with_aug,
        extract_predictions=lambda _pred: [],
        build_detection_boxes=_build_detection_boxes,
        score_aug_iou_disagreement=_score_aug_iou,
        score_by_strategy=lambda *args, **kwargs: (0.0, {"args": args, "kwargs": kwargs}),
        normalize_strategy_name=lambda name: str(name).strip().lower(),
        random_seed=7,
        round_index=1,
    )
    assert len(rows) == 1
    assert rows[0]["sample_id"] == "sample-a"
    assert rows[0]["score"] == pytest.approx(0.42)
    assert len(seen_rows) == 2
