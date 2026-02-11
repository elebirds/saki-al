from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.base import TrainArtifact

ToFloatFn = Callable[[Any, float], float]


def resolve_save_dir(train_output: Any, model: Any) -> Path:
    save_dir_raw = getattr(train_output, "save_dir", None)
    if not save_dir_raw and getattr(model, "trainer", None) is not None:
        save_dir_raw = getattr(model.trainer, "save_dir", None)
    if not save_dir_raw:
        raise RuntimeError("failed to locate YOLO save directory")
    return Path(str(save_dir_raw))


def copy_best_weights(*, save_dir: Path, workspace: Workspace) -> Path:
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


def collect_optional_artifacts(*, save_dir: Path, workspace: Workspace) -> list[TrainArtifact]:
    extra_artifacts: list[TrainArtifact] = []
    confusion_candidates = [
        ("confusion_matrix.png", "confusion_matrix"),
        ("confusion_matrix_normalized.png", "confusion_matrix_normalized"),
    ]
    for filename, kind in confusion_candidates:
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
                content_type="image/png",
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
        for key, value in raw_metrics.items():
            try:
                metrics[str(key)] = float(value)
            except Exception:
                continue
    if history:
        latest = history[-1]
        metrics.setdefault("map50", to_float(latest.get("map50"), 0.0))
        metrics.setdefault("map50_95", to_float(latest.get("map50_95"), 0.0))
        metrics.setdefault("precision", to_float(latest.get("precision"), 0.0))
        metrics.setdefault("recall", to_float(latest.get("recall"), 0.0))
    return metrics

