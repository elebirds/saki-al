import hashlib
import random
from typing import Any


def _seed_from(sample_id: str, salt: str) -> int:
    h = hashlib.sha256(f"{sample_id}:{salt}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def uncertainty_1_minus_max_conf(sample_id: str) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "uncertainty"))
    max_conf = rng.random()
    score = 1.0 - max_conf
    return score, {"max_conf": max_conf}


def aug_iou_disagreement(sample_id: str) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "aug_iou"))
    raw_iou = rng.uniform(0.0, 1.0)
    score = 1.0 - raw_iou
    return score, {"aug_iou": raw_iou}


def random_baseline(sample_id: str) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "random"))
    score = rng.random()
    return score, {"rand": score}


def plugin_native_strategy(sample_id: str) -> tuple[float, dict[str, Any]]:
    rng = random.Random(_seed_from(sample_id, "plugin_native"))
    uncertainty = rng.random()
    disagreement = rng.random()
    score = 0.6 * uncertainty + 0.4 * disagreement
    return score, {"native_uncertainty": uncertainty, "native_disagreement": disagreement}


def score_by_strategy(strategy: str, sample_id: str) -> tuple[float, dict[str, Any]]:
    key = (strategy or "").lower()
    if key in {"uncertainty", "uncertainty_1_minus_max_conf"}:
        return uncertainty_1_minus_max_conf(sample_id)
    if key in {"iou_diff", "aug_iou_disagreement"}:
        return aug_iou_disagreement(sample_id)
    if key in {"random", "random_baseline"}:
        return random_baseline(sample_id)
    if key in {"plugin_native", "plugin_native_strategy"}:
        return plugin_native_strategy(sample_id)
    return uncertainty_1_minus_max_conf(sample_id)
