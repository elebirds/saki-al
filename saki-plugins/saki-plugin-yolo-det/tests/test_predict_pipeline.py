from __future__ import annotations

from pathlib import Path
from threading import Event

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
