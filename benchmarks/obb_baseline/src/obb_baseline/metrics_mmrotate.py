from __future__ import annotations

from importlib import import_module
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence

def _resolve_module(module_name: str) -> object | None:
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return None


_metrics_module = _resolve_module("mmrotate.evaluation.metrics")
if _metrics_module is None:
    _DOTAMetricBase = None
else:
    _DOTAMetricBase = getattr(_metrics_module, "DOTAMetric", None)

if _DOTAMetricBase is None:
    class _DOTAMetricBase:  # type: ignore[no-redef]
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = (args, kwargs)

        def compute_metrics(self, results: Sequence[object]) -> dict[str, object]:
            _ = results
            return {}


_registry_module = _resolve_module("mmrotate.registry")
_MMROTATE_METRICS = getattr(_registry_module, "METRICS", None) if _registry_module is not None else None


OverlapsFn = Callable[[Sequence[Sequence[float]], Sequence[Sequence[float]]], object]


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        converted = tolist()
        if isinstance(converted, list):
            return converted
        if isinstance(converted, tuple):
            return list(converted)
        return [converted]
    if isinstance(value, Iterable) and not isinstance(value, str | bytes):
        return list(value)
    return [value]


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_field(instance: object, name: str) -> object:
    if isinstance(instance, Mapping):
        return instance.get(name)
    return getattr(instance, name, None)


def _normalize_boxes(value: object) -> list[list[float]]:
    rows = _as_list(value)
    normalized: list[list[float]] = []
    for row in rows:
        row_values = _as_list(row)
        if not row_values:
            continue
        normalized.append([_as_float(item) for item in row_values])
    return normalized


def _normalize_labels(value: object) -> list[int]:
    return [int(_as_float(item)) for item in _as_list(value)]


def _normalize_scores(value: object, *, length: int) -> list[float]:
    scores = [_as_float(item, default=1.0) for item in _as_list(value)]
    if not scores:
        return [1.0] * length
    if len(scores) < length:
        return scores + [1.0] * (length - len(scores))
    return scores[:length]


def _to_dota_pair(ground_truth: object, prediction: object) -> tuple[dict[str, object], dict[str, object]]:
    gt_boxes = _normalize_boxes(_extract_field(ground_truth, "bboxes"))
    gt_labels = _normalize_labels(_extract_field(ground_truth, "labels"))
    gt_len = min(len(gt_boxes), len(gt_labels))
    gt_payload = {
        "bboxes": gt_boxes[:gt_len],
        "labels": gt_labels[:gt_len],
    }

    pred_boxes = _normalize_boxes(_extract_field(prediction, "bboxes"))
    pred_labels = _normalize_labels(_extract_field(prediction, "labels"))
    pred_len = min(len(pred_boxes), len(pred_labels))
    pred_scores = _normalize_scores(
        _extract_field(prediction, "scores"),
        length=pred_len,
    )
    pred_payload = {
        "bboxes": pred_boxes[:pred_len],
        "labels": pred_labels[:pred_len],
        "scores": pred_scores[:pred_len],
    }
    return gt_payload, pred_payload


def _as_overlap_matrix(value: object) -> list[list[float]]:
    rows = _as_list(value)
    matrix: list[list[float]] = []
    for row in rows:
        row_values = _as_list(row)
        matrix.append([_as_float(item) for item in row_values])
    return matrix


def _resolve_default_overlaps_fn() -> OverlapsFn:
    candidates = (
        ("mmrotate.structures.bbox", "rbbox_overlaps"),
        ("mmrotate.structures.bbox", "box_iou_rotated"),
        ("mmcv.ops", "box_iou_rotated"),
    )
    for module_name, attr_name in candidates:
        module = _resolve_module(module_name)
        if module is None:
            continue
        overlaps = getattr(module, attr_name, None)
        if callable(overlaps):
            return overlaps
    raise RuntimeError(
        "No rotated IoU implementation found. Provide overlaps_fn or install mmrotate/mmcv."
    )


def _to_overlap_tensor(boxes: Sequence[Sequence[float]]) -> object | None:
    torch_module = _resolve_module("torch")
    if torch_module is None:
        return None
    tensor = getattr(torch_module, "tensor", None)
    if not callable(tensor):
        return None
    dtype = getattr(torch_module, "float32", None)
    try:
        return tensor(boxes, dtype=dtype)
    except TypeError:
        return tensor(boxes)
    except Exception:
        return None


def _compute_overlap_matrix(
    *,
    pred_box: Sequence[float],
    candidate_gt_boxes: Sequence[Sequence[float]],
    overlaps: OverlapsFn,
) -> list[list[float]]:
    try:
        overlap_values = overlaps([pred_box], candidate_gt_boxes)
    except AttributeError as exc:
        if "size" not in str(exc):
            raise
        pred_tensor = _to_overlap_tensor([pred_box])
        gt_tensor = _to_overlap_tensor(candidate_gt_boxes)
        if pred_tensor is None or gt_tensor is None:
            raise
        overlap_values = overlaps(pred_tensor, gt_tensor)
    return _as_overlap_matrix(overlap_values)


def compute_precision_recall_f1_from_dota_results(
    dota_results: Sequence[tuple[object, object]],
    *,
    score_thr: float,
    iou_thr: float = 0.5,
    overlaps_fn: OverlapsFn | None = None,
) -> dict[str, float]:
    overlaps = overlaps_fn or _resolve_default_overlaps_fn()

    true_positive = 0
    false_positive = 0
    false_negative = 0

    for ground_truth, prediction in dota_results:
        gt_payload, pred_payload = _to_dota_pair(ground_truth, prediction)
        gt_boxes = gt_payload["bboxes"]
        gt_labels = gt_payload["labels"]
        pred_boxes = pred_payload["bboxes"]
        pred_labels = pred_payload["labels"]
        pred_scores = pred_payload["scores"]

        matched_gt_indices: set[int] = set()
        gt_count = len(gt_boxes)

        filtered_predictions = [
            (index, score)
            for index, score in enumerate(pred_scores)
            if score >= score_thr
        ]
        filtered_predictions.sort(key=lambda item: item[1], reverse=True)

        for pred_index, _ in filtered_predictions:
            pred_label = pred_labels[pred_index]
            candidate_gt_indices = [
                gt_index
                for gt_index in range(gt_count)
                if gt_labels[gt_index] == pred_label and gt_index not in matched_gt_indices
            ]
            if not candidate_gt_indices:
                false_positive += 1
                continue

            candidate_gt_boxes = [gt_boxes[gt_index] for gt_index in candidate_gt_indices]
            overlap_matrix = _compute_overlap_matrix(
                pred_box=pred_boxes[pred_index],
                candidate_gt_boxes=candidate_gt_boxes,
                overlaps=overlaps,
            )
            overlap_row = overlap_matrix[0] if overlap_matrix else []
            best_iou = -1.0
            best_gt_index = -1
            for local_index, iou_value in enumerate(overlap_row):
                if iou_value > best_iou:
                    best_iou = iou_value
                    best_gt_index = local_index

            if best_gt_index >= 0 and best_iou >= iou_thr:
                matched_gt_indices.add(candidate_gt_indices[best_gt_index])
                true_positive += 1
            else:
                false_positive += 1

        false_negative += gt_count - len(matched_gt_indices)

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) > 0 else 0.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _extract_dota_results(results: Sequence[object]) -> list[tuple[object, object]]:
    pairs: list[tuple[object, object]] = []
    for item in results:
        if isinstance(item, tuple | list) and len(item) == 2:
            pairs.append((item[0], item[1]))
            continue
        if not isinstance(item, Mapping):
            continue

        ground_truth = item.get("gt_instances")
        prediction = item.get("pred_instances")
        if ground_truth is None:
            ground_truth = item.get("gt")
        if prediction is None:
            prediction = item.get("pred")
        if ground_truth is None or prediction is None:
            continue
        pairs.append((ground_truth, prediction))
    return pairs


def _register_metric(cls: type[object]) -> type[object]:
    if _MMROTATE_METRICS is None:
        return cls
    register_module = getattr(_MMROTATE_METRICS, "register_module", None)
    if not callable(register_module):
        return cls
    return register_module()(cls)


@_register_metric
class BenchmarkDOTAMetric(_DOTAMetricBase):
    def __init__(
        self,
        *args: object,
        score_thr: float = 0.5,
        iou_thr: float = 0.5,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.score_thr = float(score_thr)
        self.iou_thr = float(iou_thr)

    def compute_metrics(self, results: Sequence[object]) -> dict[str, Any]:
        base_metrics = super().compute_metrics(results)
        metrics = dict(base_metrics) if isinstance(base_metrics, Mapping) else {}
        prf_metrics = compute_precision_recall_f1_from_dota_results(
            _extract_dota_results(results),
            score_thr=self.score_thr,
            iou_thr=self.iou_thr,
        )
        metrics.update(prf_metrics)
        return metrics


__all__ = [
    "BenchmarkDOTAMetric",
    "compute_precision_recall_f1_from_dota_results",
]
