from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping


@dataclass(slots=True)
class RunMetadata:
    benchmark_name: str
    split_manifest_hash: str
    model_name: str
    preset: str
    holdout_seed: int
    split_seed: int
    train_seed: int
    artifact_paths: dict[str, str]
    train_time_sec: float | None
    infer_time_ms: float | None
    peak_mem_mb: float | None
    param_count: int | None
    checkpoint_size_mb: float | None


_MODEL_TO_PRESET = {
    "oriented_rcnn_r50": {
        "preset": "oriented_rcnn",
        "base_config": "oriented_rcnn/oriented-rcnn-le90_r50_fpn_1x_dota.py",
    },
    "roi_transformer_r50": {
        "preset": "roi_transformer",
        "base_config": "roi_trans/roi-trans-le90_r50_fpn_1x_dota.py",
    },
    "r3det_r50": {
        "preset": "r3det",
        "base_config": "r3det/r3det-oc_r50_fpn_1x_dota.py",
    },
    "rtmdet_rotated_m": {
        "preset": "rtmdet_rotated",
        "base_config": "rotated_rtmdet/rotated_rtmdet_m-3x-dota.py",
    },
}

_STANDARD_METRIC_KEYS = (
    "mAP50_95",
    "mAP50",
    "precision",
    "recall",
    "f1",
)


def _parse_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _compute_f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _find_metric_value(
    raw_metrics: Mapping[str, object],
    *keys: str,
) -> float | None:
    for key in keys:
        if key in raw_metrics:
            return _parse_optional_float(raw_metrics.get(key))
    return None


def render_mmrotate_config(
    *,
    model_name: str,
    data_root: Path,
    work_dir: Path,
    train_seed: int,
    score_thr: float,
    classes: tuple[str, ...] | list[str],
) -> str:
    try:
        preset = _MODEL_TO_PRESET[model_name]["preset"]
        base_config = _MODEL_TO_PRESET[model_name]["base_config"]
    except KeyError as exc:
        raise ValueError(f"unsupported mmrotate model_name: {model_name!r}") from exc

    normalized_classes = tuple(str(name) for name in classes)
    return (
        "# Auto-generated MMRotate config shim.\n"
        f'_base_ = ["mmrotate::{base_config}"]\n'
        f'preset = "{preset}"\n'
        f'data_root = r"{data_root.as_posix()}"\n'
        f"classes = {normalized_classes!r}\n"
        f"class_names = {normalized_classes!r}\n"
        f"num_classes = {len(normalized_classes)}\n"
        f'work_dir = r"{work_dir.as_posix()}"\n'
        f"train_seed = {int(train_seed)}\n"
        f"score_thr = {float(score_thr)}\n"
    )


def build_mmrotate_train_command(
    *,
    model_name: str,
    run_dir: Path,
    generated_config: Path,
    work_dir: Path,
    train_seed: int,
    device: str,
) -> list[str]:
    _ = (model_name, run_dir)
    return [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/mmrotate",
        "python",
        "-m",
        "obb_baseline.runners_mmrotate",
        "--config",
        str(generated_config),
        "--work-dir",
        str(work_dir),
        "--seed",
        str(train_seed),
        "--device",
        str(device),
    ]


def normalize_mmrotate_metrics(raw_metrics: Mapping[str, object]) -> dict[str, float | None]:
    metrics = {
        "mAP50_95": _find_metric_value(raw_metrics, "mAP50_95", "dota/mAP", "mAP", "bbox_mAP"),
        "mAP50": _find_metric_value(raw_metrics, "mAP50", "dota/AP50", "AP50", "bbox_mAP_50"),
        "precision": _find_metric_value(raw_metrics, "precision"),
        "recall": _find_metric_value(raw_metrics, "recall"),
    }
    metrics["f1"] = _compute_f1(metrics["precision"], metrics["recall"])
    return metrics


def write_mmrotate_metrics_json(
    *,
    metrics_path: Path,
    run_metadata: RunMetadata,
    status: str,
    normalized_metrics: Mapping[str, object],
) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "benchmark_name": run_metadata.benchmark_name,
        "split_manifest_hash": run_metadata.split_manifest_hash,
        "model_name": run_metadata.model_name,
        "preset": run_metadata.preset,
        "holdout_seed": run_metadata.holdout_seed,
        "split_seed": run_metadata.split_seed,
        "train_seed": run_metadata.train_seed,
        "status": status,
        "mAP50_95": normalized_metrics.get("mAP50_95"),
        "mAP50": normalized_metrics.get("mAP50"),
        "precision": normalized_metrics.get("precision"),
        "recall": normalized_metrics.get("recall"),
        "f1": normalized_metrics.get("f1"),
        "train_time_sec": run_metadata.train_time_sec,
        "infer_time_ms": run_metadata.infer_time_ms,
        "peak_mem_mb": run_metadata.peak_mem_mb,
        "param_count": run_metadata.param_count,
        "checkpoint_size_mb": run_metadata.checkpoint_size_mb,
        "artifact_paths": dict(run_metadata.artifact_paths),
    }
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MMRotate runner child-process entrypoint")
    parser.add_argument("--config", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--device", required=True)
    return parser.parse_args(argv)


def _parse_generated_config(generated_config: Path) -> dict[str, object]:
    namespace: dict[str, object] = {}
    safe_builtins = {"len": len, "tuple": tuple, "list": list}
    exec(
        generated_config.read_text(encoding="utf-8"),
        {"__builtins__": safe_builtins},
        namespace,
    )

    parsed: dict[str, object] = {}
    for key in ("preset", "classes", "class_names", "num_classes", "data_root", "work_dir", "train_seed", "score_thr"):
        if key in namespace:
            parsed[key] = namespace[key]

    classes = parsed.get("classes")
    if isinstance(classes, list | tuple):
        parsed["classes"] = tuple(str(name) for name in classes)

    class_names = parsed.get("class_names")
    if isinstance(class_names, list | tuple):
        parsed["class_names"] = tuple(str(name) for name in class_names)
    elif "classes" in parsed:
        parsed["class_names"] = parsed["classes"]

    if "num_classes" not in parsed and isinstance(parsed.get("class_names"), tuple):
        parsed["num_classes"] = len(parsed["class_names"])
    elif "num_classes" in parsed:
        parsed["num_classes"] = int(parsed["num_classes"])  # type: ignore[arg-type]
    return parsed


def _set_key_recursively(node: object, *, key: str, value: object) -> None:
    if isinstance(node, MutableMapping):
        if key in node:
            node[key] = value
        for child in node.values():
            _set_key_recursively(child, key=key, value=value)
    elif isinstance(node, list):
        for child in node:
            _set_key_recursively(child, key=key, value=value)


def _set_num_classes(node: object, *, num_classes: int) -> None:
    _set_key_recursively(node, key="num_classes", value=num_classes)


def _patch_dataset_cfg(node: object, *, data_root: str | None, classes: tuple[str, ...] | None) -> None:
    if isinstance(node, MutableMapping):
        if data_root is not None and "data_root" in node:
            node["data_root"] = data_root
        if classes is not None:
            if "metainfo" in node and isinstance(node["metainfo"], MutableMapping):
                node["metainfo"]["classes"] = classes
            elif "metainfo" in node:
                node["metainfo"] = {"classes": classes}
            if "classes" in node:
                node["classes"] = classes
        for child in node.values():
            _patch_dataset_cfg(child, data_root=data_root, classes=classes)
    elif isinstance(node, list):
        for child in node:
            _patch_dataset_cfg(child, data_root=data_root, classes=classes)


def _apply_runtime_overrides(
    cfg: MutableMapping[str, object],
    *,
    parsed_generated_config: Mapping[str, object],
    work_dir: Path,
    train_seed: int,
    device: str,
) -> None:
    cfg["work_dir"] = str(work_dir)
    cfg["train_cfg"] = cfg.get("train_cfg", {})
    cfg["randomness"] = {"seed": train_seed}

    data_root = parsed_generated_config.get("data_root")
    normalized_data_root = str(data_root) if data_root is not None else None
    class_names = parsed_generated_config.get("class_names")
    normalized_classes: tuple[str, ...] | None = None
    if isinstance(class_names, tuple):
        normalized_classes = class_names

    for loader_key in ("train_dataloader", "val_dataloader", "test_dataloader"):
        _patch_dataset_cfg(
            cfg.get(loader_key),
            data_root=normalized_data_root,
            classes=normalized_classes,
        )

    num_classes = parsed_generated_config.get("num_classes")
    if isinstance(num_classes, int):
        _set_num_classes(cfg.get("model"), num_classes=num_classes)

    score_thr = parsed_generated_config.get("score_thr")
    if isinstance(score_thr, float | int):
        _set_key_recursively(cfg.get("model"), key="score_thr", value=float(score_thr))

    if device == "cpu":
        cfg["device"] = "cpu"
    elif device.startswith("cuda:"):
        _, _, device_id = device.partition(":")
        if device_id:
            os.environ["CUDA_VISIBLE_DEVICES"] = device_id


def _collect_artifacts(work_dir: Path) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    last_checkpoint_file = work_dir / "last_checkpoint"
    if last_checkpoint_file.exists():
        checkpoint = last_checkpoint_file.read_text(encoding="utf-8").strip()
        if checkpoint:
            artifacts["last_checkpoint"] = checkpoint

    best_ckpts = sorted(work_dir.glob("best*.pth"))
    if best_ckpts:
        artifacts["best_checkpoint"] = str(best_ckpts[-1])
    return artifacts


def _execute_mmrotate_pipeline(
    *,
    generated_config: Path,
    parsed_generated_config: Mapping[str, object],
    work_dir: Path,
    train_seed: int,
    device: str,
) -> dict[str, dict[str, object]]:
    try:
        from mmengine.config import Config
        from mmengine.registry import init_default_scope
        from mmengine.runner import Runner
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MMRotate runtime dependencies are unavailable. "
            "Install mmengine/mmrotate in benchmarks/obb_baseline/envs/mmrotate."
        ) from exc

    cfg = Config.fromfile(str(generated_config))
    _apply_runtime_overrides(
        cfg,
        parsed_generated_config=parsed_generated_config,
        work_dir=work_dir,
        train_seed=train_seed,
        device=device,
    )

    init_default_scope("mmrotate")
    runner = Runner.from_cfg(cfg)
    runner.train()
    raw_metrics = runner.test()
    if not isinstance(raw_metrics, Mapping):
        raw_metrics = {}
    return {
        "raw_metrics": dict(raw_metrics),
        "artifacts": _collect_artifacts(work_dir),
    }


def _write_raw_outputs(
    *,
    work_dir: Path,
    raw_metrics: Mapping[str, object],
    artifacts: Mapping[str, object],
) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "raw_metrics.json").write_text(
        json.dumps(dict(raw_metrics), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (work_dir / "artifacts.json").write_text(
        json.dumps(dict(artifacts), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    generated_config = Path(args.config)
    work_dir = Path(args.work_dir)
    parsed_generated_config = _parse_generated_config(generated_config)
    execution_result = _execute_mmrotate_pipeline(
        generated_config=generated_config,
        parsed_generated_config=parsed_generated_config,
        work_dir=work_dir,
        train_seed=args.seed,
        device=args.device,
    )
    raw_metrics = execution_result.get("raw_metrics", {})
    artifacts = execution_result.get("artifacts", {})
    _write_raw_outputs(
        work_dir=work_dir,
        raw_metrics=raw_metrics if isinstance(raw_metrics, Mapping) else {},
        artifacts=artifacts if isinstance(artifacts, Mapping) else {},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
