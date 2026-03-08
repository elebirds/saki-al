from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from saki_plugin_sdk.strategies.aug_iou import build_detection_boxes, score_aug_iou_disagreement


CANONICAL_UNCERTAINTY_STRATEGY = "uncertainty_1_minus_max_conf"
CANONICAL_AUG_IOU_STRATEGY = "aug_iou_disagreement"
CANONICAL_RANDOM_STRATEGY = "random_baseline"


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def score_random_baseline(
    sample_id: str,
    *,
    random_seed: int = 0,
) -> tuple[float, dict[str, Any]]:
    digest = hashlib.sha256(f"{int(random_seed)}:{sample_id}".encode("utf-8")).hexdigest()
    score = int(digest[:8], 16) / float(0xFFFFFFFF)
    score = _clamp01(float(score))
    return score, {
        "strategy": CANONICAL_RANDOM_STRATEGY,
        "random_seed": int(random_seed),
        "rand": score,
    }


def score_uncertainty_1_minus_max_conf(
    predictions: Sequence[Mapping[str, Any]],
) -> tuple[float, dict[str, Any]]:
    conf_values = [float(item.get("confidence") or 0.0) for item in predictions]
    max_conf = max(conf_values) if conf_values else 0.0
    max_conf = _clamp01(float(max_conf))
    score = _clamp01(1.0 - max_conf)
    return score, {
        "strategy": CANONICAL_UNCERTAINTY_STRATEGY,
        "max_conf": max_conf,
        "pred_count": len(predictions),
    }


def score_aug_iou_disagreement_from_rows(
    predictions_by_aug: Sequence[Sequence[Mapping[str, Any]]],
    *,
    iou_mode: str = "obb",
    boundary_d: float = 3.0,
) -> tuple[float, dict[str, Any]]:
    boxes_by_aug = [build_detection_boxes(rows) for rows in predictions_by_aug]
    score, reason = score_aug_iou_disagreement(
        boxes_by_aug,
        iou_mode=iou_mode,
        boundary_d=boundary_d,
    )
    merged = {
        "strategy": CANONICAL_AUG_IOU_STRATEGY,
        **dict(reason or {}),
    }
    return float(score), merged


def normalize_strategy_name(strategy: str) -> str:
    return (strategy or "").strip().lower()


def score_by_strategy(
    strategy: str,
    sample_id: str,
    *,
    random_seed: int = 0,
    round_index: int = 1,
    predictions: Sequence[Mapping[str, Any]] | None = None,
    predictions_by_aug: Sequence[Sequence[Mapping[str, Any]]] | None = None,
    aug_iou_mode: str = "obb",
    aug_iou_boundary_d: float = 3.0,
) -> tuple[float, dict[str, Any]]:
    del round_index
    key = normalize_strategy_name(strategy)
    if key == CANONICAL_UNCERTAINTY_STRATEGY:
        if predictions is None:
            raise ValueError("strategy=uncertainty_1_minus_max_conf requires predictions")
        return score_uncertainty_1_minus_max_conf(predictions)
    if key == CANONICAL_AUG_IOU_STRATEGY:
        if predictions_by_aug is None:
            raise ValueError("strategy=aug_iou_disagreement requires predictions_by_aug")
        return score_aug_iou_disagreement_from_rows(
            predictions_by_aug,
            iou_mode=aug_iou_mode,
            boundary_d=aug_iou_boundary_d,
        )
    if key == CANONICAL_RANDOM_STRATEGY:
        return score_random_baseline(sample_id, random_seed=random_seed)
    raise ValueError(f"unsupported strategy: {strategy}")
