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


def _normalize_step_type(step_type: str | None) -> str:
    return str(step_type or "").strip().lower()


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


def _ensure_mapping(metrics: object) -> Mapping[str, object]:
    if not isinstance(metrics, Mapping):
        raise PluginMetricContractError(f"{METRIC_CONTRACT_ERROR_PREFIX}: metrics must be an object")
    if not metrics:
        raise PluginMetricContractError(f"{METRIC_CONTRACT_ERROR_PREFIX}: metrics must not be empty")
    return metrics


def _validate_required_and_allowed(
    *,
    metrics: dict[str, float],
    required_keys: tuple[str, ...],
    allowed_keys: frozenset[str],
    step_type: str,
) -> dict[str, float]:
    extra = sorted(key for key in metrics.keys() if key not in allowed_keys)
    if extra:
        raise PluginMetricContractError(
            f"{METRIC_CONTRACT_ERROR_PREFIX}: step_type={step_type} has non-canonical metrics: {extra}"
        )

    missing = [key for key in required_keys if key not in metrics]
    if missing:
        raise PluginMetricContractError(
            f"{METRIC_CONTRACT_ERROR_PREFIX}: step_type={step_type} missing required metrics: {missing}"
        )

    return {key: metrics[key] for key in required_keys}


def validate_final_metrics(*, step_type: str, metrics: object) -> dict[str, float]:
    normalized_step_type = _normalize_step_type(step_type)
    if normalized_step_type not in {"train", "eval"}:
        if metrics is None:
            return {}
        return _normalize_metrics(_ensure_mapping(metrics))

    normalized = _normalize_metrics(_ensure_mapping(metrics))
    if normalized_step_type == "train":
        return _validate_required_and_allowed(
            metrics=normalized,
            required_keys=TRAIN_REQUIRED_KEYS,
            allowed_keys=_TRAIN_ALLOWED,
            step_type=normalized_step_type,
        )
    return _validate_required_and_allowed(
        metrics=normalized,
        required_keys=EVAL_REQUIRED_KEYS,
        allowed_keys=_EVAL_ALLOWED,
        step_type=normalized_step_type,
    )


def validate_metric_event(
    *,
    step_type: str,
    metrics: object,
    is_final: bool,
) -> dict[str, Any]:
    normalized_step_type = _normalize_step_type(step_type)
    if normalized_step_type not in {"train", "eval"}:
        if not isinstance(metrics, Mapping):
            return {}
        return {str(key): value for key, value in metrics.items()}

    normalized = _normalize_metrics(_ensure_mapping(metrics))
    if normalized_step_type == "train":
        extra = sorted(key for key in normalized.keys() if key not in _TRAIN_ALLOWED)
        if extra:
            raise PluginMetricContractError(
                f"{METRIC_CONTRACT_ERROR_PREFIX}: step_type=train metric event has non-canonical metrics: {extra}"
            )
        if is_final:
            missing = [key for key in TRAIN_REQUIRED_KEYS if key not in normalized]
            if missing:
                raise PluginMetricContractError(
                    f"{METRIC_CONTRACT_ERROR_PREFIX}: step_type=train final metric event missing required metrics: {missing}"
                )
        return dict(normalized)

    # eval metric event must be full final canonical set.
    _ = is_final
    return _validate_required_and_allowed(
        metrics=normalized,
        required_keys=EVAL_REQUIRED_KEYS,
        allowed_keys=_EVAL_ALLOWED,
        step_type="eval",
    )
