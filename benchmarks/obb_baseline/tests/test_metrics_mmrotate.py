from __future__ import annotations

import importlib
import sys
import types

import pytest


def test_compute_precision_recall_f1_from_dota_results_counts_tp_fp_fn_with_score_filter() -> None:
    from obb_baseline.metrics_mmrotate import compute_precision_recall_f1_from_dota_results

    def _fake_overlaps(pred_boxes, gt_boxes):
        matrix: list[list[float]] = []
        for pred_box in pred_boxes:
            row: list[float] = []
            for gt_box in gt_boxes:
                row.append(1.0 if pred_box[0] == gt_box[0] else 0.0)
            matrix.append(row)
        return matrix

    metrics = compute_precision_recall_f1_from_dota_results(
        [
            (
                {
                    "bboxes": [
                        [11, 0, 0, 0, 0],
                        [22, 0, 0, 0, 0],
                    ],
                    "labels": [0, 1],
                },
                {
                    "bboxes": [
                        [11, 0, 0, 0, 0],
                        [99, 0, 0, 0, 0],
                        [22, 0, 0, 0, 0],
                    ],
                    "labels": [0, 0, 1],
                    "scores": [0.95, 0.80, 0.30],
                },
            )
        ],
        score_thr=0.5,
        iou_thr=0.5,
        overlaps_fn=_fake_overlaps,
    )

    assert metrics == {
        "precision": pytest.approx(0.5, abs=1e-6),
        "recall": pytest.approx(0.5, abs=1e-6),
        "f1": pytest.approx(0.5, abs=1e-6),
    }


def test_compute_precision_recall_f1_from_dota_results_retries_with_tensor_inputs_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from obb_baseline.metrics_mmrotate import compute_precision_recall_f1_from_dota_results

    class FakeTensor:
        def __init__(self, rows: list[list[float]]) -> None:
            self._rows = rows

        def size(self, dim: int) -> int:
            if dim == -1:
                return len(self._rows[0]) if self._rows else 0
            if dim == 0:
                return len(self._rows)
            raise ValueError(dim)

        def tolist(self) -> list[list[float]]:
            return self._rows

    def _fake_tensor(data, dtype=None):  # noqa: ANN001
        _ = dtype
        return FakeTensor([list(map(float, row)) for row in data])

    fake_torch = types.SimpleNamespace(
        tensor=_fake_tensor,
        float32=object(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    def _fake_tensor_only_overlaps(pred_boxes, gt_boxes):  # noqa: ANN001
        _ = pred_boxes.size(-1)
        _ = gt_boxes.size(-1)
        pred_rows = pred_boxes.tolist()
        gt_rows = gt_boxes.tolist()
        return [
            [1.0 if pred_row[0] == gt_row[0] else 0.0 for gt_row in gt_rows]
            for pred_row in pred_rows
        ]

    metrics = compute_precision_recall_f1_from_dota_results(
        [
            (
                {
                    "bboxes": [[11, 0, 0, 0, 0]],
                    "labels": [0],
                },
                {
                    "bboxes": [[11, 0, 0, 0, 0]],
                    "labels": [0],
                    "scores": [0.95],
                },
            )
        ],
        score_thr=0.5,
        iou_thr=0.5,
        overlaps_fn=_fake_tensor_only_overlaps,
    )

    assert metrics == {
        "precision": pytest.approx(1.0, abs=1e-6),
        "recall": pytest.approx(1.0, abs=1e-6),
        "f1": pytest.approx(1.0, abs=1e-6),
    }


def test_benchmark_dota_metric_registers_and_emits_precision_recall_f1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        def __init__(self) -> None:
            self.registered: dict[str, type[object]] = {}

        def register_module(self, *args, **kwargs):  # noqa: ANN002, ANN003
            _ = (args, kwargs)

            def _decorator(cls: type[object]) -> type[object]:
                self.registered[cls.__name__] = cls
                return cls

            return _decorator

    class FakeDOTAMetric:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            _ = (args, kwargs)

        def compute_metrics(self, results):  # noqa: ANN001
            _ = results
            return {"dota/mAP": 0.42, "dota/AP50": 0.66}

    def _fake_overlaps(pred_boxes, gt_boxes):  # noqa: ANN001
        matrix: list[list[float]] = []
        for pred_box in pred_boxes:
            row: list[float] = []
            for gt_box in gt_boxes:
                row.append(1.0 if pred_box[0] == gt_box[0] else 0.0)
            matrix.append(row)
        return matrix

    registry = FakeRegistry()
    monkeypatch.delitem(sys.modules, "obb_baseline.metrics_mmrotate", raising=False)
    monkeypatch.setitem(sys.modules, "mmrotate", types.ModuleType("mmrotate"))

    registry_module = types.ModuleType("mmrotate.registry")
    registry_module.METRICS = registry  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mmrotate.registry", registry_module)

    evaluation_module = types.ModuleType("mmrotate.evaluation")
    monkeypatch.setitem(sys.modules, "mmrotate.evaluation", evaluation_module)

    evaluation_metrics_module = types.ModuleType("mmrotate.evaluation.metrics")
    evaluation_metrics_module.DOTAMetric = FakeDOTAMetric  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mmrotate.evaluation.metrics", evaluation_metrics_module)

    structures_module = types.ModuleType("mmrotate.structures")
    monkeypatch.setitem(sys.modules, "mmrotate.structures", structures_module)

    bbox_module = types.ModuleType("mmrotate.structures.bbox")
    bbox_module.rbbox_overlaps = _fake_overlaps  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mmrotate.structures.bbox", bbox_module)

    module = importlib.import_module("obb_baseline.metrics_mmrotate")
    assert "BenchmarkDOTAMetric" in registry.registered

    metric = module.BenchmarkDOTAMetric(score_thr=0.5, iou_thr=0.5)
    metrics = metric.compute_metrics(
        [
            {
                "gt_instances": {
                    "bboxes": [
                        [11, 0, 0, 0, 0],
                        [22, 0, 0, 0, 0],
                    ],
                    "labels": [0, 1],
                },
                "pred_instances": {
                    "bboxes": [
                        [11, 0, 0, 0, 0],
                        [99, 0, 0, 0, 0],
                        [22, 0, 0, 0, 0],
                    ],
                    "labels": [0, 0, 1],
                    "scores": [0.95, 0.80, 0.30],
                },
            }
        ]
    )

    assert metrics["dota/mAP"] == 0.42
    assert metrics["dota/AP50"] == 0.66
    assert metrics["precision"] == pytest.approx(0.5, abs=1e-6)
    assert metrics["recall"] == pytest.approx(0.5, abs=1e-6)
    assert metrics["f1"] == pytest.approx(0.5, abs=1e-6)
