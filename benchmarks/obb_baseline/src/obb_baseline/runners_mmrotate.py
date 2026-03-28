from __future__ import annotations

import argparse
import collections
from collections import abc as collections_abc
import json
import math
import os
from dataclasses import dataclass, replace
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

_AMP_UNSAFE_PRESETS = {
    "r3det",
}


def _apply_python_compat_shims() -> None:
    if not hasattr(collections, "Sequence"):
        collections.Sequence = collections_abc.Sequence  # type: ignore[attr-defined]


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
    mmrotate_batch_size: int = 2,
    mmrotate_workers: int = 2,
    mmrotate_amp: bool = False,
    mmrotate_epochs: int = 36,
    mmrotate_train_aug_preset: str = "default",
    mmrotate_anchor_ratio_preset: str = "default",
    mmrotate_roi_bbox_loss_preset: str = "smooth_l1",
    mmrotate_boundary_aux_preset: str = "none",
    mmrotate_topology_aux_preset: str = "none",
) -> str:
    try:
        preset = _MODEL_TO_PRESET[model_name]["preset"]
        base_config = _MODEL_TO_PRESET[model_name]["base_config"]
    except KeyError as exc:
        raise ValueError(f"unsupported mmrotate model_name: {model_name!r}") from exc

    normalized_classes = tuple(str(name) for name in classes)
    normalized_data_root = f"{data_root.as_posix().rstrip('/')}/"
    return (
        "# Auto-generated MMRotate config shim.\n"
        f'_base_ = ["mmrotate::{base_config}"]\n'
        "custom_imports = dict(\n"
        "    imports=['obb_baseline.metrics_mmrotate', 'obb_baseline.mmrotate_stage3'],\n"
        "    allow_failed_imports=False,\n"
        ")\n"
        f'preset = "{preset}"\n'
        f'data_root = r"{normalized_data_root}"\n'
        f"classes = {normalized_classes!r}\n"
        f"class_names = {normalized_classes!r}\n"
        f"num_classes = {len(normalized_classes)}\n"
        f"mmrotate_batch_size = {int(mmrotate_batch_size)}\n"
        f"mmrotate_workers = {int(mmrotate_workers)}\n"
        f"mmrotate_amp = {bool(mmrotate_amp)}\n"
        f"mmrotate_epochs = {int(mmrotate_epochs)}\n"
        f'mmrotate_train_aug_preset = "{str(mmrotate_train_aug_preset)}"\n'
        f'mmrotate_anchor_ratio_preset = "{str(mmrotate_anchor_ratio_preset)}"\n'
        f'mmrotate_roi_bbox_loss_preset = "{str(mmrotate_roi_bbox_loss_preset)}"\n'
        f'mmrotate_boundary_aux_preset = "{str(mmrotate_boundary_aux_preset)}"\n'
        f'mmrotate_topology_aux_preset = "{str(mmrotate_topology_aux_preset)}"\n'
        f"score_thr = {float(score_thr)}\n"
        "train_dataloader = dict(\n"
        "    dataset=dict(\n"
        "        data_root=data_root,\n"
        "        ann_file='train/labelTxt/',\n"
        "        data_prefix=dict(img_path='train/images/'),\n"
        "        metainfo=dict(classes=class_names),\n"
        "    )\n"
        ")\n"
        "val_dataloader = dict(\n"
        "    dataset=dict(\n"
        "        data_root=data_root,\n"
        "        ann_file='val/labelTxt/',\n"
        "        data_prefix=dict(img_path='val/images/'),\n"
        "        metainfo=dict(classes=class_names),\n"
        "    )\n"
        ")\n"
        "test_dataloader = dict(\n"
        "    dataset=dict(\n"
        "        data_root=data_root,\n"
        "        ann_file='test/labelTxt/',\n"
        "        data_prefix=dict(img_path='test/images/'),\n"
        "        metainfo=dict(classes=class_names),\n"
        "    )\n"
        ")\n"
        "val_evaluator = dict(\n"
        "    type='BenchmarkDOTAMetric',\n"
        "    metric='mAP',\n"
        "    score_thr=score_thr,\n"
        "    iou_thrs=[0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],\n"
        ")\n"
        "test_evaluator = val_evaluator\n"
        "default_hooks = dict(\n"
        "    checkpoint=dict(\n"
        "        type='CheckpointHook',\n"
        "        interval=-1,\n"
        "        save_last=True,\n"
        "        save_best='dota/mAP',\n"
        "        rule='greater',\n"
        "        max_keep_ckpts=1,\n"
        "    )\n"
        ")\n"
        f'work_dir = r"{work_dir.as_posix()}"\n'
        f"train_seed = {int(train_seed)}\n"
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
        "precision": _find_metric_value(raw_metrics, "precision", "dota/precision"),
        "recall": _find_metric_value(raw_metrics, "recall", "dota/recall"),
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


def _load_json_mapping(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    return {}


def _merge_artifact_paths(
    *,
    work_dir: Path,
    base_paths: Mapping[str, str],
    parsed_artifacts: Mapping[str, object],
) -> dict[str, str]:
    merged = dict(base_paths)
    merged.setdefault("work_dir", str(work_dir))
    raw_metrics_path = work_dir / "raw_metrics.json"
    artifacts_path = work_dir / "artifacts.json"
    if raw_metrics_path.exists():
        merged["raw_metrics"] = str(raw_metrics_path)
    if artifacts_path.exists():
        merged["artifacts_json"] = str(artifacts_path)
    for key, value in parsed_artifacts.items():
        if value is None:
            continue
        merged[str(key)] = str(value)
    return merged


def parse_mmrotate_outputs(
    *,
    work_dir: Path,
    metrics_path: Path,
    run_metadata: RunMetadata,
    execution_status: str,
) -> None:
    raw_metrics = _load_json_mapping(work_dir / "raw_metrics.json")
    parsed_artifacts = _load_json_mapping(work_dir / "artifacts.json")
    merged_artifact_paths = _merge_artifact_paths(
        work_dir=work_dir,
        base_paths=run_metadata.artifact_paths,
        parsed_artifacts=parsed_artifacts,
    )
    metadata = replace(run_metadata, artifact_paths=merged_artifact_paths)

    if execution_status == "succeeded":
        normalized_metrics = normalize_mmrotate_metrics(raw_metrics)
    else:
        normalized_metrics = {
            "mAP50_95": None,
            "mAP50": None,
            "precision": None,
            "recall": None,
            "f1": None,
        }
    write_mmrotate_metrics_json(
        metrics_path=metrics_path,
        run_metadata=metadata,
        status=execution_status,
        normalized_metrics=normalized_metrics,
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
    safe_builtins = {"len": len, "tuple": tuple, "list": list, "dict": dict}
    exec(
        generated_config.read_text(encoding="utf-8"),
        {"__builtins__": safe_builtins},
        namespace,
    )

    parsed: dict[str, object] = {}
    for key in (
        "preset",
        "classes",
        "class_names",
        "num_classes",
        "data_root",
        "work_dir",
        "train_seed",
        "score_thr",
        "mmrotate_batch_size",
        "mmrotate_workers",
        "mmrotate_amp",
        "mmrotate_epochs",
        "mmrotate_train_aug_preset",
        "mmrotate_anchor_ratio_preset",
        "mmrotate_roi_bbox_loss_preset",
        "mmrotate_boundary_aux_preset",
        "mmrotate_topology_aux_preset",
    ):
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
    for key in ("mmrotate_batch_size", "mmrotate_workers"):
        if key in parsed and parsed[key] is not None:
            parsed[key] = int(parsed[key])  # type: ignore[arg-type]
    if "mmrotate_amp" in parsed:
        parsed["mmrotate_amp"] = bool(parsed["mmrotate_amp"])
    if "mmrotate_epochs" in parsed:
        parsed["mmrotate_epochs"] = int(parsed["mmrotate_epochs"])  # type: ignore[arg-type]
    for key in (
        "mmrotate_train_aug_preset",
        "mmrotate_anchor_ratio_preset",
        "mmrotate_roi_bbox_loss_preset",
        "mmrotate_boundary_aux_preset",
        "mmrotate_topology_aux_preset",
    ):
        if key in parsed and parsed[key] is not None:
            parsed[key] = str(parsed[key])
    return parsed


def _resolve_orcnn_anchor_ratios(preset: str) -> list[float]:
    if preset == "slender_v1":
        return [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    return [0.5, 1.0, 2.0]


def _remove_random_flip_from_pipeline(node: object) -> None:
    if isinstance(node, MutableMapping):
        pipeline = node.get("pipeline")
        if isinstance(pipeline, list):
            node["pipeline"] = [
                step for step in pipeline
                if not (isinstance(step, MutableMapping) and str(step.get("type")) == "mmdet.RandomFlip")
            ]
        for child in node.values():
            _remove_random_flip_from_pipeline(child)
    elif isinstance(node, list):
        for child in node:
            _remove_random_flip_from_pipeline(child)


def _apply_orcnn_stage3_overrides(
    cfg: MutableMapping[str, object],
    *,
    train_aug_preset: str,
    anchor_ratio_preset: str,
    roi_bbox_loss_preset: str,
    boundary_aux_preset: str,
    topology_aux_preset: str,
) -> None:
    if train_aug_preset == "spectrogram_v1":
        _remove_random_flip_from_pipeline(cfg.get("train_dataloader"))

    rpn_head = cfg.get("model", {}).get("rpn_head") if isinstance(cfg.get("model"), MutableMapping) else None
    if isinstance(rpn_head, MutableMapping):
        anchor_generator = rpn_head.get("anchor_generator")
        if isinstance(anchor_generator, MutableMapping):
            anchor_generator["ratios"] = _resolve_orcnn_anchor_ratios(anchor_ratio_preset)

    roi_head = cfg.get("model", {}).get("roi_head") if isinstance(cfg.get("model"), MutableMapping) else None
    if not isinstance(roi_head, MutableMapping):
        return

    bbox_head = roi_head.get("bbox_head")
    bbox_heads = bbox_head if isinstance(bbox_head, list) else [bbox_head]
    for head in bbox_heads:
        if not isinstance(head, MutableMapping):
            continue
        if roi_bbox_loss_preset == "gwd":
            head["reg_decoded_bbox"] = True
            head["loss_bbox"] = {
                "type": "GDLoss",
                "loss_type": "gwd",
                "loss_weight": 2.0,
            }
        if boundary_aux_preset == "boundary_v1" or topology_aux_preset == "topology_v1":
            head["type"] = "OrientedBoundaryAuxBBoxHead"
            head["boundary_aux_loss_weight"] = 0.2 if boundary_aux_preset == "boundary_v1" else 0.0
            head["boundary_aux_target_size"] = 7
            head["boundary_band_width"] = 1
            head["topology_aux_loss_weight"] = 0.1 if topology_aux_preset == "topology_v1" else 0.0
            head["centerline_width"] = 1
    if boundary_aux_preset == "boundary_v1" or topology_aux_preset == "topology_v1":
        roi_head["type"] = "OrientedBoundaryAuxRoIHead"


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


def _set_dataloader_runtime(
    *,
    loader: object,
    batch_size: int | None = None,
    num_workers: int | None = None,
) -> None:
    if not isinstance(loader, MutableMapping):
        return
    if batch_size is not None:
        loader["batch_size"] = batch_size
    if num_workers is not None:
        loader["num_workers"] = num_workers
        loader["persistent_workers"] = num_workers > 0
        loader["pin_memory"] = num_workers > 0


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


def _scale_epoch_value(value: object, scale: float, *, minimum: int = 1) -> object:
    if not isinstance(value, (int, float)):
        return value
    scaled = value * scale
    if not math.isfinite(scaled):
        return value
    scaled_int = int(round(scaled))
    return max(minimum, scaled_int)


def _scale_scheduler_milestones(milestones: object, scale: float) -> object:
    def _scale(item: object) -> object:
        if isinstance(item, (int, float)):
            return _scale_epoch_value(item, scale)
        return item

    if isinstance(milestones, list):
        return [_scale(item) for item in milestones]
    if isinstance(milestones, tuple):
        return tuple(_scale(item) for item in milestones)
    return milestones


def _scale_param_scheduler(node: object | None, *, scale: float) -> None:
    entries: list[object] = []
    if isinstance(node, list):
        entries = node
    elif isinstance(node, MutableMapping):
        entries = [node]
    else:
        return

    for scheduler in entries:
        if not isinstance(scheduler, MutableMapping):
            continue
        if "begin" in scheduler:
            scheduler["begin"] = _scale_epoch_value(
                scheduler.get("begin"),
                scale,
                minimum=0,
            )
        if "end" in scheduler:
            scheduler["end"] = _scale_epoch_value(scheduler.get("end"), scale)
        if "T_max" in scheduler:
            scheduler["T_max"] = _scale_epoch_value(scheduler.get("T_max"), scale)
        if "T_0" in scheduler:
            scheduler["T_0"] = _scale_epoch_value(scheduler.get("T_0"), scale)
        if "milestones" in scheduler:
            scheduler["milestones"] = _scale_scheduler_milestones(
                scheduler.get("milestones"),
                scale,
            )
        begin = scheduler.get("begin")
        end = scheduler.get("end")
        if isinstance(begin, (int, float)) and isinstance(end, (int, float)) and end <= begin:
            scheduler["end"] = max(1, int(end))
            scheduler["begin"] = max(0, int(scheduler["end"]) - 1)


def _apply_runtime_overrides(
    cfg: MutableMapping[str, object],
    *,
    parsed_generated_config: Mapping[str, object],
    work_dir: Path,
    train_seed: int,
    device: str,
) -> None:
    cfg["work_dir"] = str(work_dir)
    train_cfg = cfg.setdefault("train_cfg", {})
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

    mmrotate_batch_size = parsed_generated_config.get("mmrotate_batch_size")
    if isinstance(mmrotate_batch_size, int):
        _set_dataloader_runtime(
            loader=cfg.get("train_dataloader"),
            batch_size=mmrotate_batch_size,
        )

    mmrotate_workers = parsed_generated_config.get("mmrotate_workers")
    if isinstance(mmrotate_workers, int):
        for loader_key in ("train_dataloader", "val_dataloader", "test_dataloader"):
            _set_dataloader_runtime(
                loader=cfg.get(loader_key),
                num_workers=mmrotate_workers,
            )

    mmrotate_amp = parsed_generated_config.get("mmrotate_amp")
    preset = parsed_generated_config.get("preset")
    amp_enabled = mmrotate_amp is True and preset not in _AMP_UNSAFE_PRESETS
    if amp_enabled:
        optim_wrapper = cfg.get("optim_wrapper")
        if isinstance(optim_wrapper, MutableMapping):
            optim_wrapper["type"] = "AmpOptimWrapper"
            optim_wrapper.setdefault("loss_scale", "dynamic")

    train_aug_preset = str(parsed_generated_config.get("mmrotate_train_aug_preset") or "default")
    anchor_ratio_preset = str(parsed_generated_config.get("mmrotate_anchor_ratio_preset") or "default")
    roi_bbox_loss_preset = str(parsed_generated_config.get("mmrotate_roi_bbox_loss_preset") or "smooth_l1")
    boundary_aux_preset = str(parsed_generated_config.get("mmrotate_boundary_aux_preset") or "none")
    topology_aux_preset = str(parsed_generated_config.get("mmrotate_topology_aux_preset") or "none")
    _apply_orcnn_stage3_overrides(
        cfg,
        train_aug_preset=train_aug_preset,
        anchor_ratio_preset=anchor_ratio_preset,
        roi_bbox_loss_preset=roi_bbox_loss_preset,
        boundary_aux_preset=boundary_aux_preset,
        topology_aux_preset=topology_aux_preset,
    )

    target_epochs = parsed_generated_config.get("mmrotate_epochs")
    if target_epochs is None:
        target_epochs = 36
    try:
        target_epochs = int(target_epochs)
    except (TypeError, ValueError):
        target_epochs = 36

    original_epochs = train_cfg.get("max_epochs")
    scale = 1.0
    if isinstance(original_epochs, (int, float)) and original_epochs > 0:
        scale = target_epochs / float(original_epochs)
    train_cfg["max_epochs"] = target_epochs
    _scale_param_scheduler(cfg.get("param_scheduler"), scale=scale)

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


def _resolve_checkpoint_path(checkpoint: str, work_dir: Path) -> Path | None:
    candidate = Path(checkpoint)
    if not candidate.is_absolute():
        candidate = work_dir / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        return None
    return candidate


def _select_mmrotate_test_checkpoint(work_dir: Path) -> Path | None:
    best_ckpts = sorted(work_dir.glob("best*.pth"))
    if best_ckpts:
        return best_ckpts[-1].resolve()

    last_checkpoint_file = work_dir / "last_checkpoint"
    if not last_checkpoint_file.exists():
        return None

    checkpoint = last_checkpoint_file.read_text(encoding="utf-8").strip()
    if not checkpoint:
        return None
    return _resolve_checkpoint_path(checkpoint, work_dir)


def _execute_mmrotate_pipeline(
    *,
    generated_config: Path,
    parsed_generated_config: Mapping[str, object],
    work_dir: Path,
    train_seed: int,
    device: str,
) -> dict[str, dict[str, object]]:
    _apply_python_compat_shims()
    try:
        from mmengine.config import Config
        from mmengine.registry import init_default_scope
        from mmengine.runner import Runner
        from mmengine.runner.checkpoint import load_checkpoint
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
    test_checkpoint = _select_mmrotate_test_checkpoint(work_dir)
    if test_checkpoint is not None:
        load_checkpoint(runner.model, str(test_checkpoint), map_location="cpu")
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
    def _to_jsonable(value: object) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, Path):
            return value.as_posix()
        if isinstance(value, Mapping):
            return {str(key): _to_jsonable(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [_to_jsonable(item) for item in value]
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            return _to_jsonable(tolist())
        item = getattr(value, "item", None)
        if callable(item):
            return _to_jsonable(item())
        return str(value)

    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "raw_metrics.json").write_text(
        json.dumps(_to_jsonable(raw_metrics), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (work_dir / "artifacts.json").write_text(
        json.dumps(_to_jsonable(artifacts), ensure_ascii=False, indent=2) + "\n",
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
