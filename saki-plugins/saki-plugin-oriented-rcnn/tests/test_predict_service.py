from __future__ import annotations

import math
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

import pytest
from PIL import Image

import saki_plugin_oriented_rcnn.predict_service as predict_service_mod
from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.predict_service import OrientedRCNNPredictService
from saki_plugin_sdk.strategies.builtin import (
    CANONICAL_AUG_IOU_STRATEGY,
    CANONICAL_RANDOM_STRATEGY,
    CANONICAL_UNCERTAINTY_STRATEGY,
    score_aug_iou_disagreement_from_rows,
    score_by_strategy,
    score_random_baseline,
)


def test_aug_iou_disagreement_boundary_inputs() -> None:
    score_empty, reason_empty = score_aug_iou_disagreement_from_rows([])
    assert score_empty == 0.0
    assert set(reason_empty.keys()) == {
        "strategy",
        "mean_iou",
        "count_gap",
        "class_gap",
        "conf_std",
        "score",
    }

    single = [[
        {"class_index": 0, "confidence": 0.6, "geometry": {"rect": {"x": 0.0, "y": 0.0, "width": 2.0, "height": 2.0}}},
        {"class_index": 0, "confidence": 0.8, "geometry": {"rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 2.0}}},
    ]]
    score_single, reason_single = score_aug_iou_disagreement_from_rows(single)
    assert math.isclose(score_single, 0.105, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(reason_single["score"]), score_single, rel_tol=1e-6, abs_tol=1e-6)

    qbox = (0.0, 0.0, 2.0, 0.0, 2.0, 2.0, 0.0, 2.0)
    same_left = [
        {"class_index": 0, "confidence": 0.9, "qbox": qbox},
        {"class_index": 1, "confidence": 0.7, "qbox": qbox},
    ]
    same_right = [
        {"class_index": 0, "confidence": 0.9, "qbox": qbox},
        {"class_index": 1, "confidence": 0.7, "qbox": qbox},
    ]
    score_same, reason_same = score_aug_iou_disagreement_from_rows([same_left, same_right])
    assert math.isclose(score_same, 0.0, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(reason_same["mean_iou"]), 1.0, rel_tol=1e-6, abs_tol=1e-6)


def test_random_baseline_score_is_stable_for_same_seed_and_pool() -> None:
    first, _ = score_random_baseline("sample-a", random_seed=101)
    second, _ = score_random_baseline("sample-a", random_seed=101)
    third, _ = score_random_baseline("sample-b", random_seed=101)
    assert first == second
    assert first != third


def test_score_by_strategy_is_strict_on_required_inputs() -> None:
    with pytest.raises(ValueError, match="requires predictions"):
        score_by_strategy(CANONICAL_UNCERTAINTY_STRATEGY, "sample-a", random_seed=1)

    with pytest.raises(ValueError, match="requires predictions_by_aug"):
        score_by_strategy(CANONICAL_AUG_IOU_STRATEGY, "sample-a", random_seed=1)


def test_score_by_strategy_routes_three_canonical_strategies() -> None:
    random_score, random_reason = score_by_strategy(CANONICAL_RANDOM_STRATEGY, "sample-a", random_seed=7)
    assert 0.0 <= random_score <= 1.0
    assert random_reason["strategy"] == CANONICAL_RANDOM_STRATEGY

    uncertainty_score, uncertainty_reason = score_by_strategy(
        CANONICAL_UNCERTAINTY_STRATEGY,
        "sample-a",
        predictions=[{"confidence": 0.85}],
    )
    assert math.isclose(uncertainty_score, 0.15, rel_tol=1e-6, abs_tol=1e-6)
    assert uncertainty_reason["strategy"] == CANONICAL_UNCERTAINTY_STRATEGY

    aug_score, aug_reason = score_by_strategy(
        CANONICAL_AUG_IOU_STRATEGY,
        "sample-a",
        predictions_by_aug=[[{"confidence": 0.6}], [{"confidence": 0.8}]],
    )
    assert 0.0 <= aug_score <= 1.0
    assert aug_reason["strategy"] == CANONICAL_AUG_IOU_STRATEGY


def test_predict_with_augmentations_rebuilds_geometry_from_restored_qbox(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    Image.fromarray(np.zeros((8, 10, 3), dtype=np.uint8)).save(image_path)

    service = OrientedRCNNPredictService(
        stop_flag=threading.Event(),
        config_service=object(),  # type: ignore[arg-type]
    )

    views = [
        SimpleNamespace(
            name="identity",
            image=np.zeros((8, 10, 3), dtype=np.uint8),
            orig_width=10,
            orig_height=8,
            width=10,
            height=8,
            spec=None,
            inverse_point=lambda x, y, _view: (x, y),
        )
    ]
    monkeypatch.setattr(predict_service_mod, "build_augmented_views", lambda *_args, **_kwargs: views)
    monkeypatch.setattr(predict_service_mod, "infer_source", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(
        service,
        "_build_entries",
        lambda **_kwargs: [
            {
                "class_index": 0,
                "class_name": "ship",
                "confidence": 0.9,
                "qbox": (0.0, 0.0, 4.0, 0.0, 4.0, 2.0, 0.0, 2.0),
                "rbox": (100.0, 100.0, 50.0, 10.0, 1.2),
                "geometry": {"rect": {"x": 0.0, "y": 0.0, "width": 4.0, "height": 2.0}},
            }
        ],
    )
    monkeypatch.setattr(
        predict_service_mod,
        "inverse_augmented_prediction_row",
        lambda row, *, view: {
            **row,
            "qbox": (2.0, 2.0, 6.0, 2.0, 6.0, 4.0, 2.0, 4.0),
            "geometry": {"rect": {"x": 2.0, "y": 2.0, "width": 4.0, "height": 2.0}},
        },
    )

    outputs = service._predict_with_augmentations(
        model=object(),
        image_path=image_path,
        classes=("ship",),
        geometry_mode="obb",
        score_thr=0.1,
        max_per_img=100,
    )
    assert len(outputs) == 1
    assert len(outputs[0]) == 1
    row = outputs[0][0]
    assert row["qbox"] == pytest.approx((2.0, 2.0, 6.0, 2.0, 6.0, 4.0, 2.0, 4.0), abs=1e-6)
    geometry = dict(row.get("geometry") or {})
    obb = dict(geometry.get("obb") or {})
    assert obb.get("cx") == pytest.approx(4.0, abs=1e-6)
    assert obb.get("cy") == pytest.approx(3.0, abs=1e-6)
    assert obb.get("width") == pytest.approx(4.0, abs=1e-6)
    assert obb.get("height") == pytest.approx(2.0, abs=1e-6)


def test_predict_with_augmentations_forwards_enabled_aug_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    Image.fromarray(np.zeros((8, 10, 3), dtype=np.uint8)).save(image_path)

    service = OrientedRCNNPredictService(
        stop_flag=threading.Event(),
        config_service=object(),  # type: ignore[arg-type]
    )
    captured: dict[str, Any] = {}

    def _fake_build_augmented_views(*_args, **kwargs):
        captured["enabled_names"] = kwargs.get("enabled_names")
        return []

    monkeypatch.setattr(predict_service_mod, "build_augmented_views", _fake_build_augmented_views)
    outputs = service._predict_with_augmentations(
        model=object(),
        image_path=image_path,
        classes=("ship",),
        geometry_mode="obb",
        score_thr=0.1,
        max_per_img=100,
        enabled_aug_names=("identity", "rot90"),
    )
    assert outputs == []
    assert captured["enabled_names"] == ("identity", "rot90")


def test_oriented_config_service_aug_iou_requires_identity() -> None:
    service = OrientedRCNNConfigService()
    cfg = service.resolve_config({}, strategy="aug_iou_disagreement")
    assert "identity" in set(cfg.aug_iou_enabled_augs)
    assert cfg.aug_iou_iou_mode == "obb"
    assert cfg.aug_iou_boundary_d == 3

    with pytest.raises(ValueError, match="must include 'identity'"):
        service.resolve_config(
            {"aug_iou_enabled_augs": ["hflip", "rot90"]},
            strategy="aug_iou_disagreement",
        )


def test_oriented_config_service_validates_aug_iou_mode_and_boundary_d() -> None:
    service = OrientedRCNNConfigService()
    with pytest.raises(Exception, match="aug_iou_iou_mode"):
        service.resolve_config(
            {"aug_iou_iou_mode": "bad_mode"},
            strategy="aug_iou_disagreement",
        )

    cfg = service.resolve_config(
        {
            "aug_iou_iou_mode": "boundary",
            "aug_iou_boundary_d": 999,
        },
        strategy="aug_iou_disagreement",
    )
    assert cfg.aug_iou_iou_mode == "boundary"
    assert cfg.aug_iou_boundary_d == 128


def test_score_samples_sync_forwards_aug_iou_mode_and_boundary_d(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample = tmp_path / "sample.png"
    Image.fromarray(np.zeros((8, 10, 3), dtype=np.uint8)).save(sample)
    service = OrientedRCNNPredictService(
        stop_flag=threading.Event(),
        config_service=object(),  # type: ignore[arg-type]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(predict_service_mod, "infer_single_image", lambda **_kwargs: {})
    monkeypatch.setattr(
        service,
        "_build_entries",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        service,
        "_predict_with_augmentations",
        lambda **_kwargs: [[{"class_index": 0, "confidence": 0.9, "geometry": {"rect": {}}}]],
    )

    def _fake_score_by_strategy(_strategy, _sample_id, **kwargs):
        captured["aug_iou_mode"] = kwargs.get("aug_iou_mode")
        captured["aug_iou_boundary_d"] = kwargs.get("aug_iou_boundary_d")
        return 0.6, {"score": 0.6}

    monkeypatch.setattr(predict_service_mod, "score_by_strategy", _fake_score_by_strategy)
    rows = service._score_samples_sync(
        model=object(),
        unlabeled_samples=[{"id": "sample-a", "local_path": str(sample)}],
        strategy="aug_iou_disagreement",
        classes=("ship",),
        geometry_mode="obb",
        score_thr=0.1,
        max_per_img=100,
        random_seed=7,
        round_index=1,
        aug_enabled_names=("identity",),
        aug_iou_mode="boundary",
        aug_iou_boundary_d=9,
    )
    assert len(rows) == 1
    assert captured["aug_iou_mode"] == "boundary"
    assert captured["aug_iou_boundary_d"] == 9
