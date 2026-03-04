from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from saki_plugin_sdk import TrainArtifact, WorkspaceProtocol
from saki_plugin_yolo_det.metrics_parser import normalize_metrics

ToFloatFn = Callable[[Any, float], float]

_TRAIN_OPTIONAL_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("confusion_matrix.png", "confusion_matrix", "image/png"),
    ("confusion_matrix_normalized.png", "confusion_matrix_normalized", "image/png"),
    ("results.csv", "train_results_csv", "text/csv"),
    ("results.png", "train_results_plot", "image/png"),
    ("args.yaml", "train_args", "application/yaml"),
    ("BoxF1_curve.png", "train_curve_f1", "image/png"),
    ("BoxPR_curve.png", "train_curve_pr", "image/png"),
    ("BoxP_curve.png", "train_curve_p", "image/png"),
    ("BoxR_curve.png", "train_curve_r", "image/png"),
)


def resolve_save_dir(train_output: Any, model: Any) -> Path:
    save_dir_raw = getattr(train_output, "save_dir", None)
    if not save_dir_raw and getattr(model, "trainer", None) is not None:
        save_dir_raw = getattr(model.trainer, "save_dir", None)
    if not save_dir_raw:
        raise RuntimeError("failed to locate YOLO save directory")
    save_dir = Path(str(save_dir_raw))
    try:
        return save_dir.resolve()
    except Exception:
        return save_dir


def copy_best_weights(*, save_dir: Path, workspace: WorkspaceProtocol) -> Path:
    best_path = save_dir / "weights" / "best.pt"
    if not best_path.exists():
        fallback = save_dir / "weights" / "last.pt"
        if fallback.exists():
            best_path = fallback
        else:
            raise RuntimeError(f"no weights artifact found under {save_dir / 'weights'}")
    final_best = workspace.artifacts_dir / "best.pt"
    shutil.copy2(best_path, final_best)
    return final_best


def collect_optional_artifacts(*, save_dir: Path, workspace: WorkspaceProtocol) -> list[TrainArtifact]:
    extra_artifacts: list[TrainArtifact] = []
    for filename, kind, content_type in _TRAIN_OPTIONAL_ARTIFACT_SPECS:
        source = save_dir / filename
        if not source.exists():
            continue
        target = workspace.artifacts_dir / filename
        shutil.copy2(source, target)
        extra_artifacts.append(
            TrainArtifact(
                kind=kind,
                name=filename,
                path=target,
                content_type=content_type,
                meta={"size": target.stat().st_size},
            )
        )
    return extra_artifacts


def extract_primary_metrics(
    *,
    train_output: Any,
    history: list[dict[str, float]],
    to_float: ToFloatFn,
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if hasattr(train_output, "results_dict"):
        raw_metrics = getattr(train_output, "results_dict", {}) or {}
        metrics.update(normalize_metrics(raw_metrics, to_float))
    if history:
        latest = history[-1]
        for key in ("map50", "map50_95", "precision", "recall", "loss"):
            if key in metrics:
                continue
            if latest.get(key) is None:
                continue
            metrics[key] = to_float(latest.get(key), 0.0)
    return metrics
