from __future__ import annotations

"""MMRotate 适配层。

边界说明：
1. 本模块屏蔽第三方框架导入细节；上层 service 不直接依赖 mmrotate API。
2. 所有重依赖都做懒加载，避免插件被扫描时因环境未安装直接崩溃。
3. 提供 train / eval / infer / pr 计算四类能力，供 train/eval/predict 复用。
"""

import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _build_mm_import_error(exc: Exception) -> RuntimeError:
    """将底层导入异常转成可诊断的运行时错误。"""
    message = str(exc or "").strip()
    if isinstance(exc, ModuleNotFoundError) and (
        getattr(exc, "name", "") == "mmcv._ext" or "mmcv._ext" in message
    ):
        return RuntimeError(
            "mmrotate runtime dependencies are not ready: missing mmcv._ext; "
            "this is usually caused by an incomplete onedl-mmcv build in profile env. "
            "please trigger profile auto-repair/rebuild with --no-build-isolation "
            f"(root={exc.__class__.__name__}: {message})"
        )

    return RuntimeError(
        "mmrotate runtime dependencies are required: onedl-mmrotate/onedl-mmdetection/onedl-mmengine "
        f"(root={exc.__class__.__name__}: {message})"
    )


def _lazy_import_mm() -> dict[str, Any]:
    try:
        from mmengine.config import Config  # type: ignore
        from mmengine.runner import Runner  # type: ignore
        from mmdet.apis import init_detector, inference_detector  # type: ignore
        from mmrotate.evaluation.functional import eval_rbbox_map  # type: ignore
        from mmrotate.structures.bbox import rbox2qbox  # type: ignore
    except Exception as exc:  # pragma: no cover - 运行时依赖
        raise _build_mm_import_error(exc) from exc

    return {
        "Config": Config,
        "Runner": Runner,
        "init_detector": init_detector,
        "inference_detector": inference_detector,
        "eval_rbbox_map": eval_rbbox_map,
        "rbox2qbox": rbox2qbox,
    }


def run_train_and_eval(
    *,
    config_path: Path,
) -> dict[str, Any]:
    mm = _lazy_import_mm()
    Config = mm["Config"]
    Runner = mm["Runner"]

    cfg = Config.fromfile(str(config_path))
    runner = Runner.from_cfg(cfg)

    runner.train()

    eval_metrics: dict[str, Any] = {}
    try:
        eval_output = runner.test()
        if isinstance(eval_output, dict):
            eval_metrics = dict(eval_output)
    except Exception:
        eval_metrics = {}

    checkpoint = _resolve_checkpoint(Path(str(cfg.work_dir)))
    loss_value = _read_last_loss(Path(str(cfg.work_dir)))

    return {
        "checkpoint": str(checkpoint),
        "eval_metrics": eval_metrics,
        "loss": float(loss_value),
        "work_dir": str(cfg.work_dir),
    }


def run_eval_only(
    *,
    config_path: Path,
    checkpoint: str,
) -> dict[str, Any]:
    mm = _lazy_import_mm()
    Config = mm["Config"]
    Runner = mm["Runner"]

    cfg = Config.fromfile(str(config_path))
    cfg.load_from = str(checkpoint)
    runner = Runner.from_cfg(cfg)

    eval_metrics: dict[str, Any] = {}
    result = runner.test()
    if isinstance(result, dict):
        eval_metrics = dict(result)

    return {
        "eval_metrics": eval_metrics,
        "work_dir": str(cfg.work_dir),
    }


def build_model(
    *,
    config_path: Path,
    checkpoint: str,
    device: str,
):
    mm = _lazy_import_mm()
    init_detector = mm["init_detector"]
    return init_detector(str(config_path), str(checkpoint), device=str(device))


def infer_source(
    *,
    model: Any,
    source: Any,
) -> dict[str, np.ndarray]:
    mm = _lazy_import_mm()
    inference_detector = mm["inference_detector"]
    rbox2qbox = mm["rbox2qbox"]

    # source 同时支持：
    # 1) str/Path：磁盘图片路径
    # 2) ndarray：内存增强图像（用于 aug_iou_disagreement）
    result = inference_detector(model, source)
    pred = getattr(result, "pred_instances", None)
    if pred is None:
        return {
            "labels": np.zeros((0,), dtype=np.int64),
            "scores": np.zeros((0,), dtype=np.float32),
            "rboxes": np.zeros((0, 5), dtype=np.float32),
            "qboxes": np.zeros((0, 8), dtype=np.float32),
        }

    labels = pred.labels.detach().cpu().numpy() if hasattr(pred, "labels") else np.zeros((0,), dtype=np.int64)
    scores = pred.scores.detach().cpu().numpy() if hasattr(pred, "scores") else np.zeros((0,), dtype=np.float32)
    bboxes = pred.bboxes.detach().cpu() if hasattr(pred, "bboxes") else None

    if bboxes is None or bboxes.numel() == 0:
        rboxes = np.zeros((0, 5), dtype=np.float32)
        qboxes = np.zeros((0, 8), dtype=np.float32)
    else:
        rboxes = bboxes.numpy().astype(np.float32)
        qboxes = rbox2qbox(bboxes).detach().cpu().numpy().astype(np.float32)

    return {
        "labels": labels.astype(np.int64),
        "scores": scores.astype(np.float32),
        "rboxes": rboxes,
        "qboxes": qboxes,
    }


def infer_single_image(
    *,
    model: Any,
    image_path: Path,
) -> dict[str, np.ndarray]:
    return infer_source(model=model, source=str(image_path))


def evaluate_micro_pr(
    *,
    config_path: Path,
    checkpoint: str,
    device: str,
) -> list[dict[str, Any]]:
    """计算 IoU=0.5 下每类 PR 明细，供上层做微平均。

    实现策略：
    1. 读取 val 标注目录（DOTA txt）。
    2. 用模型逐图推理，构建 per-class 检测结果。
    3. 调用 mmrotate 的 `eval_rbbox_map`（box_type=qbox）得到标准明细。
    """
    mm = _lazy_import_mm()
    Config = mm["Config"]
    eval_rbbox_map = mm["eval_rbbox_map"]

    cfg = Config.fromfile(str(config_path))
    class_names = tuple(cfg.get("classes") or cfg.get("metainfo", {}).get("classes") or ())
    if not class_names:
        return []

    dataset_cfg = cfg.val_dataloader.dataset
    data_root = Path(str(dataset_cfg.data_root))
    ann_dir = data_root / str(dataset_cfg.ann_file)
    img_dir = data_root / str(dataset_cfg.data_prefix["img_path"])

    image_paths = sorted(img_dir.glob("*.png"))
    if not image_paths:
        return []

    class_to_idx = {name: idx for idx, name in enumerate(class_names)}
    model = build_model(config_path=config_path, checkpoint=checkpoint, device=device)

    det_results: list[list[np.ndarray]] = []
    annotations: list[dict[str, Any]] = []

    for image_path in image_paths:
        pred = infer_single_image(model=model, image_path=image_path)
        labels = pred["labels"]
        scores = pred["scores"]
        qboxes = pred["qboxes"]

        per_cls: list[np.ndarray] = []
        for cls_idx in range(len(class_names)):
            idxs = np.where(labels == cls_idx)[0]
            if len(idxs) == 0:
                per_cls.append(np.zeros((0, 9), dtype=np.float32))
                continue
            cls_q = qboxes[idxs]
            cls_s = scores[idxs].reshape(-1, 1)
            per_cls.append(np.concatenate([cls_q, cls_s], axis=1).astype(np.float32))
        det_results.append(per_cls)

        gt_file = ann_dir / f"{image_path.stem}.txt"
        gt_boxes: list[list[float]] = []
        gt_labels: list[int] = []
        gt_boxes_ignore: list[list[float]] = []
        gt_labels_ignore: list[int] = []

        if gt_file.exists():
            for raw in gt_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("imagesource:") or line.startswith("gsd:"):
                    continue
                parts = line.split()
                if len(parts) < 9:
                    continue
                try:
                    coords = [float(v) for v in parts[:8]]
                except Exception:
                    continue
                cls_name = str(parts[8]).strip()
                if cls_name not in class_to_idx:
                    continue
                difficulty = 0
                if len(parts) >= 10:
                    try:
                        difficulty = int(float(parts[9]))
                    except Exception:
                        difficulty = 0
                if difficulty > 100:
                    gt_boxes_ignore.append(coords)
                    gt_labels_ignore.append(class_to_idx[cls_name])
                else:
                    gt_boxes.append(coords)
                    gt_labels.append(class_to_idx[cls_name])

        annotations.append(
            {
                "bboxes": np.asarray(gt_boxes, dtype=np.float32).reshape((-1, 8)),
                "labels": np.asarray(gt_labels, dtype=np.int64).reshape((-1,)),
                "bboxes_ignore": np.asarray(gt_boxes_ignore, dtype=np.float32).reshape((-1, 8)),
                "labels_ignore": np.asarray(gt_labels_ignore, dtype=np.int64).reshape((-1,)),
            }
        )

    _mean_ap, details = eval_rbbox_map(
        det_results,
        annotations,
        iou_thr=0.5,
        use_07_metric=True,
        box_type="qbox",
        dataset=list(class_names),
        logger="silent",
        nproc=1,
    )
    return [dict(row) for row in details]


def _resolve_checkpoint(work_dir: Path) -> Path:
    if not work_dir.exists():
        raise RuntimeError(f"work_dir not found: {work_dir}")

    best_files = sorted(work_dir.glob("best*.pth"))
    if best_files:
        return best_files[-1]

    last = work_dir / "latest.pth"
    if last.exists():
        return last

    all_ckpts = sorted(work_dir.glob("*.pth"))
    if all_ckpts:
        return all_ckpts[-1]

    raise RuntimeError(f"no checkpoint found in work_dir: {work_dir}")


def _read_last_loss(work_dir: Path) -> float:
    """尽力读取最后一个 loss 值。

    说明：MMEngine 在不同版本下日志落盘格式可能不同，
    所以这里采用多路径兜底，任何失败都回退 0.0。
    """
    candidates = [
        work_dir / "vis_data" / "scalars.json",
        work_dir / "scalars.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            value = _read_loss_from_scalars(path)
            if value is not None:
                return float(value)
        except Exception:
            continue

    # 再兜底找 *.log.json（line-delimited json）
    for path in sorted(work_dir.glob("*.log.json")):
        try:
            value = _read_loss_from_logjson(path)
            if value is not None:
                return float(value)
        except Exception:
            continue

    return 0.0


def _read_loss_from_scalars(path: Path) -> float | None:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    payload = json.loads(text)
    if isinstance(payload, dict):
        # 常见结构：{"loss": [{"value": ...}, ...]}
        for key in ("loss", "train/loss", "loss_total"):
            series = payload.get(key)
            if isinstance(series, list) and series:
                last = series[-1]
                if isinstance(last, dict):
                    for f in ("value", "data", "y"):
                        if f in last:
                            try:
                                return float(last[f])
                            except Exception:
                                pass
                try:
                    return float(last)
                except Exception:
                    pass
    return None


def _read_loss_from_logjson(path: Path) -> float | None:
    last_loss: float | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        for key in ("loss", "train/loss", "loss_total"):
            if key in row:
                try:
                    value = float(row[key])
                    if math.isfinite(value):
                        last_loss = value
                except Exception:
                    continue
    return last_loss
