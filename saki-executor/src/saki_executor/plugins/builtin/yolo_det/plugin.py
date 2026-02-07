from __future__ import annotations

import asyncio
import csv
import json
import math
from pathlib import Path
import shutil
import threading
from typing import Any, Callable

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None  # type: ignore
try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.base import EventCallback, ExecutorPlugin, TrainArtifact, TrainOutput
from saki_executor.strategies.aug_iou import (
    build_detection_boxes,
    score_aug_iou_disagreement,
)
from saki_executor.strategies.builtin import score_by_strategy


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _rect_to_corners(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    return [
        (x, y),
        (x + w, y),
        (x + w, y + h),
        (x, y + h),
    ]


def _rotated_rect_to_corners(cx: float, cy: float, w: float, h: float, angle_deg: float) -> list[tuple[float, float]]:
    rad = math.radians(angle_deg)
    cos_v = math.cos(rad)
    sin_v = math.sin(rad)
    dx = w / 2.0
    dy = h / 2.0
    base = [(-dx, -dy), (dx, -dy), (dx, dy), (-dx, dy)]
    corners: list[tuple[float, float]] = []
    for px, py in base:
        rx = px * cos_v - py * sin_v + cx
        ry = px * sin_v + py * cos_v + cy
        corners.append((rx, ry))
    return corners


def _normalize_obb_corners(
    corners: list[tuple[float, float]],
    width: float,
    height: float,
) -> list[float]:
    safe_w = max(1.0, width)
    safe_h = max(1.0, height)
    values: list[float] = []
    for x, y in corners:
        values.append(_clamp(x / safe_w, 0.0, 1.0))
        values.append(_clamp(y / safe_h, 0.0, 1.0))
    return values


def _infer_image_hw(path: Path) -> tuple[int, int]:
    if Image is None:
        raise RuntimeError("Pillow is required for yolo_det_v1 plugin")
    with Image.open(path) as img:
        w, h = img.size
        return h, w


class YoloDetectionPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        self._stop_flag = threading.Event()

    @property
    def plugin_id(self) -> str:
        return "yolo_det_v1"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_job_types(self) -> list[str]:
        return ["train_detection"]

    @property
    def supported_strategies(self) -> list[str]:
        return [
            "aug_iou_disagreement_v1",
            "aug_iou_disagreement",
            "uncertainty_1_minus_max_conf",
            "random_baseline",
            "plugin_native_strategy",
        ]

    def validate_params(self, params: dict[str, Any]) -> None:
        epochs = _to_int(params.get("epochs", 30), 30)
        batch = _to_int(params.get("batch", params.get("batch_size", 16)), 16)
        imgsz = _to_int(params.get("imgsz", 640), 640)
        topk = _to_int(params.get("topk", 200), 200)
        if epochs <= 0:
            raise ValueError("epochs must be > 0")
        if batch <= 0:
            raise ValueError("batch must be > 0")
        if imgsz <= 0:
            raise ValueError("imgsz must be > 0")
        if topk <= 0:
            raise ValueError("topk must be > 0")

    async def prepare_data(
        self,
        workspace: Workspace,
        labels: list[dict[str, Any]],
        samples: list[dict[str, Any]],
        annotations: list[dict[str, Any]],
    ) -> None:
        data_root = workspace.data_dir
        images_dir = data_root / "images" / "train"
        labels_dir = data_root / "labels" / "train"
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)

        # 标签索引：保持后端顺序，保证 round 间一致性。
        label_id_to_idx: dict[str, int] = {}
        names: dict[int, str] = {}
        for idx, item in enumerate(labels):
            label_id = str(item.get("id") or "")
            if not label_id:
                continue
            label_id_to_idx[label_id] = idx
            names[idx] = str(item.get("name") or f"class_{idx}")

        sample_map: dict[str, dict[str, Any]] = {}
        for sample in samples:
            sample_id = str(sample.get("id") or "")
            local_path_raw = str(sample.get("local_path") or "")
            if not sample_id or not local_path_raw:
                continue
            src = Path(local_path_raw)
            if not src.exists():
                continue
            dst = images_dir / f"{sample_id}.jpg"
            shutil.copy2(src, dst)
            sample_map[sample_id] = {
                "image_path": dst,
                "width": _to_int(sample.get("width"), 0),
                "height": _to_int(sample.get("height"), 0),
            }

        ann_by_sample: dict[str, list[str]] = {}
        skipped_count = 0
        for ann in annotations:
            sample_id = str(ann.get("sample_id") or "")
            category_id = str(ann.get("category_id") or "")
            if sample_id not in sample_map or category_id not in label_id_to_idx:
                skipped_count += 1
                continue

            item = sample_map[sample_id]
            h = int(item["height"] or 0)
            w = int(item["width"] or 0)
            if h <= 0 or w <= 0:
                try:
                    h, w = _infer_image_hw(Path(item["image_path"]))
                except Exception:
                    skipped_count += 1
                    continue

            cls_idx = label_id_to_idx[category_id]
            line = self._annotation_to_yolo_obb_line(ann=ann, cls_idx=cls_idx, width=w, height=h)
            if not line:
                skipped_count += 1
                continue
            ann_by_sample.setdefault(sample_id, []).append(line)

        for sample_id, item in sample_map.items():
            label_file = labels_dir / f"{sample_id}.txt"
            lines = ann_by_sample.get(sample_id, [])
            label_file.write_text("\n".join(lines), encoding="utf-8")

        dataset_yaml = {
            "path": str(data_root.resolve()),
            "train": "images/train",
            "val": "images/train",
            "names": names,
        }
        (data_root / "dataset.yaml").write_text(
            json.dumps(dataset_yaml, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        (data_root / "dataset_manifest.json").write_text(
            json.dumps(
                {
                    "sample_count": len(sample_map),
                    "annotation_count": sum(len(v) for v in ann_by_sample.values()),
                    "label_count": len(names),
                    "skipped_annotation_count": skipped_count,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    async def train(
        self,
        workspace: Workspace,
        params: dict[str, Any],
        emit: EventCallback,
    ) -> TrainOutput:
        self._stop_flag.clear()
        epochs = _to_int(params.get("epochs", 30), 30)
        batch = _to_int(params.get("batch", params.get("batch_size", 16)), 16)
        imgsz = _to_int(params.get("imgsz", 640), 640)
        patience = _to_int(params.get("patience", 20), 20)
        device = params.get("device", 0)
        base_model = str(params.get("base_model", "yolov8n-obb.pt") or "yolov8n-obb.pt")

        dataset_yaml = workspace.data_dir / "dataset.yaml"
        if not dataset_yaml.exists():
            raise RuntimeError(f"dataset file not found: {dataset_yaml}")

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"YOLO training started base_model={base_model} "
                    f"epochs={epochs} batch={batch} imgsz={imgsz} patience={patience} device={device}"
                ),
            },
        )

        train_result = await asyncio.to_thread(
            self._run_train_sync,
            workspace=workspace,
            dataset_yaml=dataset_yaml,
            base_model=base_model,
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            patience=patience,
            device=device,
        )

        for idx, metrics_row in enumerate(train_result["history"], start=1):
            await emit(
                "progress",
                {
                    "epoch": idx,
                    "step": idx,
                    "total_steps": max(1, len(train_result["history"])),
                    "eta_sec": 0,
                },
            )
            await emit("metric", {"step": idx, "epoch": idx, "metrics": metrics_row})

        metrics = dict(train_result["metrics"])
        report_path = workspace.artifacts_dir / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "metrics": metrics,
                    "history": train_result["history"],
                    "train_dir": str(train_result["save_dir"]),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        best_path = Path(train_result["best_path"])

        await emit(
            "artifact",
            {
                "kind": "weights",
                "name": "best.pt",
                "uri": str(best_path),
                "meta": {"size": best_path.stat().st_size},
            },
        )
        await emit(
            "artifact",
            {
                "kind": "report",
                "name": "report.json",
                "uri": str(report_path),
                "meta": {"size": report_path.stat().st_size},
            },
        )

        return TrainOutput(
            metrics=metrics,
            artifacts=[
                TrainArtifact(
                    kind="weights",
                    name="best.pt",
                    path=best_path,
                    content_type="application/octet-stream",
                ),
                TrainArtifact(
                    kind="report",
                    name="report.json",
                    path=report_path,
                    content_type="application/json",
                ),
            ],
        )

    async def predict_unlabeled(
        self,
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self.predict_unlabeled_batch(workspace, unlabeled_samples, strategy, params)

    async def predict_unlabeled_batch(
        self,
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        topk = max(1, _to_int(params.get("topk", 200), 200))
        base_model = str(params.get("base_model", "yolov8n-obb.pt") or "yolov8n-obb.pt")
        conf = _to_float(params.get("predict_conf", 0.1), 0.1)
        imgsz = _to_int(params.get("imgsz", 640), 640)
        device = params.get("device", 0)

        best_path = workspace.artifacts_dir / "best.pt"
        model_path = str(best_path if best_path.exists() else base_model)

        candidates = await asyncio.to_thread(
            self._score_unlabeled_sync,
            model_path=model_path,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            conf=conf,
            imgsz=imgsz,
            device=device,
        )
        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return candidates[:topk]

    async def stop(self, job_id: str) -> None:
        del job_id
        self._stop_flag.set()

    def _annotation_to_yolo_obb_line(
        self,
        *,
        ann: dict[str, Any],
        cls_idx: int,
        width: int,
        height: int,
    ) -> str | None:
        obb = ann.get("obb")
        corners: list[tuple[float, float]] | None = None

        if isinstance(obb, dict):
            points = obb.get("points")
            if isinstance(points, list) and len(points) >= 4:
                parsed: list[tuple[float, float]] = []
                for point in points[:4]:
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        parsed = []
                        break
                    parsed.append((_to_float(point[0]), _to_float(point[1])))
                if len(parsed) == 4:
                    corners = parsed
            if corners is None and {"cx", "cy", "width", "height"}.issubset(obb.keys()):
                cx = _to_float(obb.get("cx"))
                cy = _to_float(obb.get("cy"))
                w = _to_float(obb.get("width"))
                h = _to_float(obb.get("height"))
                angle = _to_float(obb.get("angle"), 0.0)
                corners = _rotated_rect_to_corners(cx, cy, w, h, angle)

        if corners is None:
            bbox = ann.get("bbox_xywh")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                x, y, w, h = [_to_float(v) for v in bbox]
                if w > 0 and h > 0:
                    corners = _rect_to_corners(x, y, w, h)

        if not corners:
            return None

        normalized = _normalize_obb_corners(corners, width=float(width), height=float(height))
        values = " ".join(f"{value:.6f}" for value in normalized)
        return f"{cls_idx} {values}"

    def _load_yolo(self):
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "ultralytics is required for yolo_det_v1 plugin, please install it in saki-executor"
            ) from exc
        return YOLO

    def _ensure_image_deps(self) -> None:
        if Image is None or np is None:
            raise RuntimeError("numpy and pillow are required for yolo_det_v1 plugin")

    def _run_train_sync(
        self,
        *,
        workspace: Workspace,
        dataset_yaml: Path,
        base_model: str,
        epochs: int,
        batch: int,
        imgsz: int,
        patience: int,
        device: Any,
    ) -> dict[str, Any]:
        if self._stop_flag.is_set():
            raise RuntimeError("training stopped before start")

        YOLO = self._load_yolo()
        model = YOLO(base_model)
        train_output = model.train(
            data=str(dataset_yaml),
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            patience=patience,
            device=device,
            project=str(workspace.root),
            name="yolo_train",
            exist_ok=True,
            verbose=False,
        )
        if self._stop_flag.is_set():
            raise RuntimeError("training stopped")

        save_dir_raw = getattr(train_output, "save_dir", None)
        if not save_dir_raw and getattr(model, "trainer", None) is not None:
            save_dir_raw = getattr(model.trainer, "save_dir", None)
        if not save_dir_raw:
            raise RuntimeError("failed to locate YOLO save directory")
        save_dir = Path(str(save_dir_raw))

        best_path = save_dir / "weights" / "best.pt"
        if not best_path.exists():
            fallback = save_dir / "weights" / "last.pt"
            if fallback.exists():
                best_path = fallback
            else:
                raise RuntimeError(f"no weights artifact found under {save_dir / 'weights'}")

        # 固定上传路径，便于 API 侧注册制品。
        final_best = workspace.artifacts_dir / "best.pt"
        shutil.copy2(best_path, final_best)

        metrics: dict[str, float] = {}
        if hasattr(train_output, "results_dict"):
            raw_metrics = getattr(train_output, "results_dict", {}) or {}
            for k, v in raw_metrics.items():
                try:
                    metrics[str(k)] = float(v)
                except Exception:
                    continue

        history = self._parse_results_csv(save_dir / "results.csv")
        if history:
            latest = history[-1]
            metrics.setdefault("map50", _to_float(latest.get("map50"), 0.0))
            metrics.setdefault("map50_95", _to_float(latest.get("map50_95"), 0.0))
            metrics.setdefault("precision", _to_float(latest.get("precision"), 0.0))
            metrics.setdefault("recall", _to_float(latest.get("recall"), 0.0))

        return {
            "metrics": metrics,
            "history": history,
            "save_dir": str(save_dir),
            "best_path": str(final_best),
        }

    def _parse_results_csv(self, path: Path) -> list[dict[str, float]]:
        if not path.exists():
            return []
        rows: list[dict[str, float]] = []
        with path.open("r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            for item in reader:
                row: dict[str, float] = {}
                map50_keys = ("metrics/mAP50(B)", "metrics/mAP50(M)", "metrics/mAP50")
                map50_95_keys = ("metrics/mAP50-95(B)", "metrics/mAP50-95(M)", "metrics/mAP50-95")
                precision_keys = ("metrics/precision(B)", "metrics/precision(M)", "metrics/precision")
                recall_keys = ("metrics/recall(B)", "metrics/recall(M)", "metrics/recall")
                row["map50"] = self._pick_metric(item, map50_keys)
                row["map50_95"] = self._pick_metric(item, map50_95_keys)
                row["precision"] = self._pick_metric(item, precision_keys)
                row["recall"] = self._pick_metric(item, recall_keys)
                rows.append(row)
        return rows

    def _pick_metric(self, row: dict[str, str], keys: tuple[str, ...]) -> float:
        for key in keys:
            if key in row and row[key] != "":
                return _to_float(row[key], 0.0)
        return 0.0

    def _score_unlabeled_sync(
        self,
        *,
        model_path: str,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        conf: float,
        imgsz: int,
        device: Any,
    ) -> list[dict[str, Any]]:
        YOLO = self._load_yolo()
        model = YOLO(model_path)
        candidates: list[dict[str, Any]] = []

        for sample in unlabeled_samples:
            if self._stop_flag.is_set():
                raise RuntimeError("sampling stopped")

            sample_id = str(sample.get("id") or "")
            local_path = str(sample.get("local_path") or "")
            if not sample_id or not local_path:
                continue
            image_path = Path(local_path)
            if not image_path.exists():
                continue

            if (strategy or "").lower() in {"aug_iou_disagreement_v1", "aug_iou_disagreement"}:
                preds_by_aug = self._predict_with_aug(
                    model=model,
                    image_path=image_path,
                    conf=conf,
                    imgsz=imgsz,
                    device=device,
                )
                boxes_by_aug = [build_detection_boxes(item) for item in preds_by_aug]
                score, reason = score_aug_iou_disagreement(boxes_by_aug)
                prediction_snapshot = {
                    "strategy": "aug_iou_disagreement_v1",
                    "aug_count": len(preds_by_aug),
                    "pred_per_aug": [len(item) for item in preds_by_aug],
                    "base_predictions": preds_by_aug[0][:30] if preds_by_aug else [],
                }
                candidates.append(
                    {
                        "sample_id": sample_id,
                        "score": score,
                        "reason": reason,
                        "prediction_snapshot": prediction_snapshot,
                    }
                )
            else:
                score, reason = score_by_strategy(strategy, sample_id)
                candidates.append({"sample_id": sample_id, "score": score, "reason": reason})

        return candidates

    def _predict_with_aug(
        self,
        *,
        model,
        image_path: Path,
        conf: float,
        imgsz: int,
        device: Any,
    ) -> list[list[dict[str, Any]]]:
        self._ensure_image_deps()
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            image = np.array(rgb)

        h, w = image.shape[:2]
        transforms: list[tuple[str, Callable[[np.ndarray], np.ndarray]]] = [
            ("identity", lambda arr: arr),
            ("hflip", lambda arr: np.ascontiguousarray(arr[:, ::-1, :])),
            ("vflip", lambda arr: np.ascontiguousarray(arr[::-1, :, :])),
            ("bright", lambda arr: np.clip(arr.astype(np.float32) * 1.2, 0, 255).astype(np.uint8)),
        ]

        results_by_aug: list[list[dict[str, Any]]] = []
        for name, transform in transforms:
            aug_img = transform(image)
            predicts = model.predict(
                source=aug_img,
                conf=conf,
                imgsz=imgsz,
                device=device,
                verbose=False,
            )
            first = predicts[0] if predicts else None
            rows = self._extract_predictions(first)
            rows = [self._inverse_aug_box(name=name, row=item, width=w, height=h) for item in rows]
            results_by_aug.append(rows)
        return results_by_aug

    def _extract_predictions(self, result) -> list[dict[str, Any]]:
        if result is None:
            return []

        rows: list[dict[str, Any]] = []
        obb = getattr(result, "obb", None)
        if obb is not None and len(obb) > 0 and hasattr(obb, "xyxy"):
            cls_values = obb.cls.cpu().tolist()
            conf_values = obb.conf.cpu().tolist()
            xyxy_values = obb.xyxy.cpu().tolist()
            for cls_id, conf, xyxy in zip(cls_values, conf_values, xyxy_values):
                rows.append(
                    {
                        "cls_id": int(cls_id),
                        "conf": float(conf),
                        "xyxy": [float(v) for v in xyxy[:4]],
                    }
                )
            return rows

        boxes = getattr(result, "boxes", None)
        if boxes is not None and len(boxes) > 0:
            cls_values = boxes.cls.cpu().tolist()
            conf_values = boxes.conf.cpu().tolist()
            xyxy_values = boxes.xyxy.cpu().tolist()
            for cls_id, conf, xyxy in zip(cls_values, conf_values, xyxy_values):
                rows.append(
                    {
                        "cls_id": int(cls_id),
                        "conf": float(conf),
                        "xyxy": [float(v) for v in xyxy[:4]],
                    }
                )
        return rows

    def _inverse_aug_box(
        self,
        *,
        name: str,
        row: dict[str, Any],
        width: int,
        height: int,
    ) -> dict[str, Any]:
        x1, y1, x2, y2 = [float(v) for v in row.get("xyxy", [0, 0, 0, 0])]
        if name == "hflip":
            x1, x2 = float(width) - x2, float(width) - x1
        elif name == "vflip":
            y1, y2 = float(height) - y2, float(height) - y1

        x1 = _clamp(x1, 0.0, float(width))
        x2 = _clamp(x2, 0.0, float(width))
        y1 = _clamp(y1, 0.0, float(height))
        y2 = _clamp(y2, 0.0, float(height))
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        return {
            "cls_id": int(row.get("cls_id", 0)),
            "conf": _to_float(row.get("conf", 0.0), 0.0),
            "xyxy": [x1, y1, x2, y2],
        }
