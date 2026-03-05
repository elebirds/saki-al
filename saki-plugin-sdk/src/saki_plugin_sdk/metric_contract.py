"""Metric contract for plugin metric events and final outputs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from saki_plugin_sdk.exceptions import METRIC_CONTRACT_ERROR_PREFIX, PluginMetricContractError

TRAIN_REQUIRED_KEYS: tuple[str, ...] = ("map50", "map50_95", "precision", "recall", "loss")
EVAL_REQUIRED_KEYS: tuple[str, ...] = ("map50", "map50_95", "precision", "recall")

_TRAIN_ALLOWED = frozenset(TRAIN_REQUIRED_KEYS)
_EVAL_ALLOWED = frozenset(EVAL_REQUIRED_KEYS)


def _normalize_task_type(task_type: str | None) -> str:
    return str(task_type or "").strip().lower()


def _normalize_metrics(metrics: Mapping[str, object]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_key, raw_value in metrics.items():
        key = str(raw_key or "").strip()
        if not key:
            raise PluginMetricContractError(f"{METRIC_CONTRACT_ERROR_PREFIX}: empty metric key is not allowed")
        try:
            value = float(raw_value)
        except Exception as exc:  # pragma: no cover - defensive
            raise PluginMetricContractError(
                f"{METRIC_CONTRACT_ERROR_PREFIX}: metric '{key}' value is not numeric"
            ) from exc
        if not math.isfinite(value):
            raise PluginMetricContractError(
                f"{METRIC_CONTRACT_ERROR_PREFIX}: metric '{key}' value must be finite"
            )
        normalized[key] = value
    return normalized


def _ensure_mapping(metrics: object, *, allow_empty: bool = False) -> Mapping[str, object]:
    if not isinstance(metrics, Mapping):
        raise PluginMetricContractError(f"{METRIC_CONTRACT_ERROR_PREFIX}: metrics must be an object")
    if not allow_empty and not metrics:
        raise PluginMetricContractError(f"{METRIC_CONTRACT_ERROR_PREFIX}: metrics must not be empty")
    return metrics


def _validate_allowed_and_ordered(
    *,
    metrics: dict[str, float],
    ordered_keys: tuple[str, ...],
    allowed_keys: frozenset[str],
    task_type: str,
) -> dict[str, float]:
    extra = sorted(key for key in metrics.keys() if key not in allowed_keys)
    if extra:
        raise PluginMetricContractError(
            f"{METRIC_CONTRACT_ERROR_PREFIX}: task_type={task_type} has non-canonical metrics: {extra}"
        )
    return {key: metrics[key] for key in ordered_keys if key in metrics}


def validate_final_metrics(*, task_type: str, metrics: object) -> dict[str, float]:
    normalized_task_type = _normalize_task_type(task_type)
    if normalized_task_type not in {"train", "eval"}:
        if metrics is None:
            return {}
        source = _ensure_mapping(metrics, allow_empty=True)
        if not source:
            return {}
        return _normalize_metrics(source)

    source = _ensure_mapping(metrics, allow_empty=True)
    if not source:
        return {}
    normalized = _normalize_metrics(source)
    if normalized_task_type == "train":
        return _validate_allowed_and_ordered(
            metrics=normalized,
            ordered_keys=TRAIN_REQUIRED_KEYS,
            allowed_keys=_TRAIN_ALLOWED,
            task_type=normalized_task_type,
        )
    return _validate_allowed_and_ordered(
        metrics=normalized,
        ordered_keys=EVAL_REQUIRED_KEYS,
        allowed_keys=_EVAL_ALLOWED,
        task_type=normalized_task_type,
    )


def validate_metric_event(
    *,
    task_type: str,
    metrics: object,
    is_final: bool,
) -> dict[str, Any]:
    normalized_task_type = _normalize_task_type(task_type)
    if normalized_task_type not in {"train", "eval"}:
        if not isinstance(metrics, Mapping):
            return {}
        return {str(key): value for key, value in metrics.items()}

    _ = is_final
    source = _ensure_mapping(metrics, allow_empty=True)
    if not source:
        return {}
    normalized = _normalize_metrics(source)
    if normalized_task_type == "train":
        return _validate_allowed_and_ordered(
            metrics=normalized,
            ordered_keys=TRAIN_REQUIRED_KEYS,
            allowed_keys=_TRAIN_ALLOWED,
            task_type="train",
        )
    return _validate_allowed_and_ordered(
        metrics=normalized,
        ordered_keys=EVAL_REQUIRED_KEYS,
        allowed_keys=_EVAL_ALLOWED,
        task_type="eval",
    )
