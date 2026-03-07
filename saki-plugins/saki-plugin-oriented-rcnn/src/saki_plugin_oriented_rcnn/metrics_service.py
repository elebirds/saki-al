from __future__ import annotations

"""指标归一化服务。

该模块的职责是把底层框架输出（MMRotate/DOTAMetric）稳定映射到
Saki SDK 的 canonical metric contract。
"""

from typing import Any, Mapping

from saki_plugin_oriented_rcnn.common import to_float
from saki_plugin_oriented_rcnn.types import CanonicalMetrics


def _find_metric_value(raw_metrics: Mapping[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        if key in raw_metrics:
            return float(to_float(raw_metrics.get(key), default))
    return float(default)


def extract_map_metrics(raw_metrics: Mapping[str, Any]) -> tuple[float, float]:
    """提取 map50 / map50_95。

    兼容不同 key 命名：
    - dota/AP50
    - AP50
    - dota/mAP
    - mAP
    """
    map50 = _find_metric_value(raw_metrics, ("dota/AP50", "AP50", "bbox_mAP_50"), 0.0)
    map50_95 = _find_metric_value(raw_metrics, ("dota/mAP", "mAP", "bbox_mAP"), map50)
    return float(map50), float(map50_95)


def compute_micro_precision_recall(eval_details: list[dict[str, Any]]) -> tuple[float, float]:
    """根据 `eval_rbbox_map` 明细计算微平均 precision/recall。

    数学定义：
    - TP_c = recall_c_last * num_gts_c
    - FP_c = TP_c * (1 / precision_c_last - 1)
    - micro precision = ΣTP / (ΣTP + ΣFP)
    - micro recall    = ΣTP / ΣGT
    """
    total_tp = 0.0
    total_fp = 0.0
    total_gt = 0.0

    for row in eval_details:
        num_gts = max(0.0, to_float(row.get("num_gts"), 0.0))
        if num_gts <= 0:
            continue

        recall_series = row.get("recall")
        precision_series = row.get("precision")

        recall_last = 0.0
        if hasattr(recall_series, "size") and getattr(recall_series, "size", 0) > 0:
            try:
                recall_last = float(recall_series[-1])
            except Exception:
                recall_last = 0.0

        precision_last = 0.0
        if hasattr(precision_series, "size") and getattr(precision_series, "size", 0) > 0:
            try:
                precision_last = float(precision_series[-1])
            except Exception:
                precision_last = 0.0

        tp = max(0.0, min(1.0, recall_last)) * num_gts
        if precision_last > 0.0:
            fp = tp * max(0.0, (1.0 / max(1e-12, precision_last)) - 1.0)
        else:
            # 当 precision 为 0 时，保守地把 FP 视作 >= TP。
            fp = tp

        total_tp += tp
        total_fp += fp
        total_gt += num_gts

    precision = total_tp / max(1e-12, total_tp + total_fp)
    recall = total_tp / max(1e-12, total_gt)

    return float(max(0.0, min(1.0, precision))), float(max(0.0, min(1.0, recall)))


def build_train_metrics(
    *,
    raw_eval_metrics: Mapping[str, Any],
    eval_details: list[dict[str, Any]],
    loss_value: float,
) -> CanonicalMetrics:
    map50, map50_95 = extract_map_metrics(raw_eval_metrics)
    precision, recall = compute_micro_precision_recall(eval_details)
    return CanonicalMetrics(
        map50=map50,
        map50_95=map50_95,
        precision=precision,
        recall=recall,
        loss=float(loss_value),
    )


def build_eval_metrics(
    *,
    raw_eval_metrics: Mapping[str, Any],
    eval_details: list[dict[str, Any]],
) -> CanonicalMetrics:
    map50, map50_95 = extract_map_metrics(raw_eval_metrics)
    precision, recall = compute_micro_precision_recall(eval_details)
    return CanonicalMetrics(
        map50=map50,
        map50_95=map50_95,
        precision=precision,
        recall=recall,
        loss=None,
    )
