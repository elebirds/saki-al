import hashlib
import random
from typing import Any


CANONICAL_UNCERTAINTY_STRATEGY = "uncertainty_1_minus_max_conf"
CANONICAL_AUG_IOU_STRATEGY = "aug_iou_disagreement"
CANONICAL_RANDOM_STRATEGY = "random_baseline"


def _seed_from(sample_id: str, salt: str, random_seed: int = 0, round_index: int = 1) -> int:
    h = hashlib.sha256(f"{sample_id}:{salt}:{random_seed}:{round_index}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def uncertainty_1_minus_max_conf(
        sample_id: str,
        *,
        random_seed: int = 0,
        round_index: int = 1,
) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "uncertainty", random_seed=random_seed, round_index=round_index))
    max_conf = rng.random()
    score = 1.0 - max_conf
    return score, {"max_conf": max_conf}


def aug_iou_disagreement(
        sample_id: str,
        *,
        random_seed: int = 0,
        round_index: int = 1,
) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "aug_iou", random_seed=random_seed, round_index=round_index))
    raw_iou = rng.uniform(0.0, 1.0)
    score = 1.0 - raw_iou
    return score, {"mean_iou": raw_iou, "strategy": "mock_aug_iou"}


def random_baseline(
        sample_id: str,
        *,
        random_seed: int = 0,
        round_index: int = 1,
) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "random", random_seed=random_seed, round_index=round_index))
    score = rng.random()
    return score, {"rand": score, "random_seed": random_seed, "round_index": round_index}


def normalize_strategy_name(strategy: str) -> str:
    return (strategy or "").strip().lower()


def score_by_strategy(
        strategy: str,
        sample_id: str,
        *,
        random_seed: int = 0,
        round_index: int = 1,
) -> tuple[float, dict[str, Any]]:
    key = normalize_strategy_name(strategy)
    if key == CANONICAL_UNCERTAINTY_STRATEGY:
        return uncertainty_1_minus_max_conf(sample_id, random_seed=random_seed, round_index=round_index)
    if key == CANONICAL_AUG_IOU_STRATEGY:
        return aug_iou_disagreement(sample_id, random_seed=random_seed, round_index=round_index)
    if key == CANONICAL_RANDOM_STRATEGY:
        return random_baseline(sample_id, random_seed=random_seed, round_index=round_index)
    raise ValueError(f"unsupported strategy: {strategy}")
