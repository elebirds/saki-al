from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from saki_plugin_sdk.strategies.builtin import normalize_strategy_name, score_by_strategy
from saki_plugin_yolo_det import predict_pipeline
from saki_plugin_yolo_det.predict_pipeline import predict_with_augmentations, score_unlabeled_samples


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
        "score_by_strategy": score_by_strategy,
        "normalize_strategy_name": normalize_strategy_name,
        "random_seed": 7,
    }
    round_1 = score_unlabeled_samples(round_index=1, **kwargs)
    round_9 = score_unlabeled_samples(round_index=9, **kwargs)

    score_1 = {row["sample_id"]: float(row["score"]) for row in round_1}
    score_9 = {row["sample_id"]: float(row["score"]) for row in round_9}
    assert score_1 == score_9
    assert all("round_index" not in (row.get("reason") or {}) for row in round_1)


def test_aug_iou_strategy_passes_qbox_rows_to_sdk_strategy(tmp_path: Path) -> None:
    sample = tmp_path / "a.jpg"
    sample.write_bytes(b"\x00")
    unlabeled_samples = [{"id": "sample-a", "local_path": str(sample)}]

    seen_rows: list[list[list[dict]]] = []

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

    def _score_by_strategy(strategy, sample_id, **kwargs):
        del strategy, sample_id
        rows_by_aug = kwargs["predictions_by_aug"]
        seen_rows.append(rows_by_aug)
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
        score_by_strategy=_score_by_strategy,
        normalize_strategy_name=normalize_strategy_name,
        random_seed=7,
        round_index=1,
    )
    assert len(rows) == 1
    assert rows[0]["sample_id"] == "sample-a"
    assert rows[0]["score"] == pytest.approx(0.42)
    assert len(seen_rows) == 1


def test_aug_iou_strategy_forwards_enabled_aug_names(tmp_path: Path) -> None:
    sample = tmp_path / "a.jpg"
    sample.write_bytes(b"\x00")
    unlabeled_samples = [{"id": "sample-a", "local_path": str(sample)}]
    seen_enabled: list[tuple[str, ...] | list[str] | None] = []

    def _predict_with_aug(**kwargs):
        seen_enabled.append(kwargs.get("enabled_aug_names"))
        return [[], []]

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
        score_by_strategy=lambda _strategy, _sample_id, **_kwargs: (0.3, {"score": 0.3}),
        normalize_strategy_name=normalize_strategy_name,
        random_seed=7,
        round_index=1,
        aug_enabled_names=("identity", "rot90"),
    )
    assert len(rows) == 1
    assert seen_enabled == [("identity", "rot90")]


def test_aug_iou_strategy_forwards_iou_mode_and_boundary_d(tmp_path: Path) -> None:
    sample = tmp_path / "a.jpg"
    sample.write_bytes(b"\x00")
    unlabeled_samples = [{"id": "sample-a", "local_path": str(sample)}]
    captured: dict[str, object] = {}

    def _score_by_strategy(_strategy, _sample_id, **kwargs):
        captured["aug_iou_mode"] = kwargs.get("aug_iou_mode")
        captured["aug_iou_boundary_d"] = kwargs.get("aug_iou_boundary_d")
        return 0.3, {"score": 0.3}

    rows = score_unlabeled_samples(
        unlabeled_samples=unlabeled_samples,
        strategy="aug_iou_disagreement",
        conf=0.25,
        imgsz=640,
        device="cpu",
        stop_flag=Event(),
        get_model=lambda: object(),
        predict_single_image=lambda **_kw: [],
        predict_with_aug=lambda **_kw: [[], []],
        extract_predictions=lambda _pred: [],
        score_by_strategy=_score_by_strategy,
        normalize_strategy_name=normalize_strategy_name,
        random_seed=7,
        round_index=1,
        aug_iou_mode="boundary",
        aug_iou_boundary_d=11,
    )
    assert len(rows) == 1
    assert captured["aug_iou_mode"] == "boundary"
    assert captured["aug_iou_boundary_d"] == 11


def test_predict_with_augmentations_batches_views_into_single_predict_call(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NpStub:
        @staticmethod
        def ascontiguousarray(value):
            return value

        @staticmethod
        def array(value):
            return value

    class _ImageHandle:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            del exc_type, exc, tb
            return False

        def convert(self, mode: str):
            assert mode == "RGB"
            return [[1, 2], [3, 4]]

    class _ImageStub:
        @staticmethod
        def open(_path: Path):
            return _ImageHandle()

    monkeypatch.setattr(
        predict_pipeline,
        "build_augmented_views",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                name="identity",
                image="img-identity",
                orig_width=16,
                orig_height=16,
                inverse_point=lambda x, y, _view: (x, y),
            ),
            SimpleNamespace(
                name="hflip",
                image="img-hflip",
                orig_width=16,
                orig_height=16,
                inverse_point=lambda x, y, _view: (x, y),
            ),
            SimpleNamespace(
                name="vflip",
                image="img-vflip",
                orig_width=16,
                orig_height=16,
                inverse_point=lambda x, y, _view: (x, y),
            ),
        ],
    )

    class _Model:
        def __init__(self) -> None:
            self.sources: list[object] = []
            self.batches: list[int] = []

        def predict(self, *, source, conf, imgsz, device, verbose, batch):
            del conf, imgsz, device, verbose
            self.sources.append(source)
            self.batches.append(batch)
            return [{"rows": [0.1 * (index + 1)]} for index, _ in enumerate(source)]

    model = _Model()
    rows_by_aug = predict_with_augmentations(
        model=model,
        image_path=Path("/tmp/fake-image"),
        conf=0.1,
        imgsz=640,
        device="cuda:0",
        ensure_image_deps=lambda: None,
        image_cls=_ImageStub,
        np_mod=_NpStub,
        extract_predictions=lambda payload: [{"confidence": payload["rows"][0]}],
        enabled_aug_names=("identity", "hflip", "vflip"),
    )

    assert len(model.sources) == 1
    assert isinstance(model.sources[0], list)
    assert len(model.sources[0]) == 3
    assert model.batches == [3]
    assert len(rows_by_aug) == 3
    assert [rows[0]["confidence"] for rows in rows_by_aug] == pytest.approx([0.1, 0.2, 0.3])


def test_aug_iou_strategy_reports_progress_per_sample(tmp_path: Path) -> None:
    sample_a = tmp_path / "a.jpg"
    sample_b = tmp_path / "b.jpg"
    sample_a.write_bytes(b"\x00")
    sample_b.write_bytes(b"\x00")
    unlabeled_samples = [
        {"id": "sample-a", "local_path": str(sample_a)},
        {"id": "sample-b", "local_path": str(sample_b)},
    ]
    progress_messages: list[tuple[int, int, str]] = []

    rows = score_unlabeled_samples(
        unlabeled_samples=unlabeled_samples,
        strategy="aug_iou_disagreement",
        conf=0.25,
        imgsz=640,
        device="cuda:0",
        stop_flag=Event(),
        get_model=lambda: object(),
        predict_single_image=lambda **_kw: [],
        predict_with_aug=lambda **_kw: [[], []],
        extract_predictions=lambda _pred: [],
        score_by_strategy=lambda _strategy, sample_id, **_kwargs: (0.3, {"sample_id": sample_id}),
        normalize_strategy_name=normalize_strategy_name,
        random_seed=7,
        round_index=1,
        progress_callback=lambda processed, total, sample_id: progress_messages.append(
            (processed, total, sample_id)
        ),
    )

    assert len(rows) == 2
    assert progress_messages == [
        (1, 2, "sample-a"),
        (2, 2, "sample-b"),
    ]
