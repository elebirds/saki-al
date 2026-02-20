from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
import threading
from typing import Any, Callable
import warnings

import httpx

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None  # type: ignore
try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

from saki_executor.steps.workspace import Workspace
from saki_executor.hardware.probe import (
    ACCELERATOR_PRIORITY,
    available_accelerators,
    normalize_accelerator_name,
    probe_hardware,
)
from saki_executor.plugins.base import EventCallback, TrainArtifact, TrainOutput
from saki_executor.plugins.builtin.yolo_det.prepare_pipeline import prepare_yolo_dataset
from saki_executor.plugins.builtin.yolo_det.metrics_parser import (
    normalize_metrics as normalize_metrics_row,
    parse_results_csv as parse_results_csv_rows,
    pick_metric as pick_metric_value,
)
from saki_executor.plugins.builtin.yolo_det.predict_pipeline import (
    predict_with_augmentations,
    score_unlabeled_samples,
)
from saki_executor.plugins.builtin.yolo_det.train_async import (
    load_prepare_stats,
    normalize_training_metrics,
    resolve_train_config,
    run_train_with_epoch_stream,
)
from saki_executor.plugins.builtin.yolo_det.train_sync_runner import run_train_sync
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


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
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


class YoloDetectionInternal:
    _CJK_FONT_CANDIDATES = (
        "PingFang SC",
        "Hiragino Sans GB",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "WenQuanYi Zen Hei",
        "Microsoft YaHei",
        "SimHei",
    )

    def __init__(self) -> None:
        self._stop_flag = threading.Event()
        self._font_setup_lock = threading.Lock()
        self._font_setup_done = False

    @property
    def plugin_id(self) -> str:
        return "yolo_det_v1"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def display_name(self) -> str:
        return "YOLO Detection (OBB)"

    @property
    def supported_step_types(self) -> list[str]:
        return [
            "train",
            "score",
            "eval",
            "export",
            "upload_artifact",
            "custom",
        ]

    @property
    def supported_strategies(self) -> list[str]:
        return [
            "aug_iou_disagreement_v1",
            "aug_iou_disagreement",
            "uncertainty_1_minus_max_conf",
            "random_baseline",
            "plugin_native_strategy",
        ]

    @property
    def supported_accelerators(self) -> list[str]:
        return ["cuda", "cpu"]

    @property
    def supports_auto_fallback(self) -> bool:
        return True

    @property
    def request_config_schema(self) -> dict[str, Any]:
        return {
            "title": "YOLO Detection Request Config",
            "fields": [
                {"key": "epochs", "label": "Epochs", "type": "integer", "required": True, "min": 1, "max": 5000},
                {"key": "batch", "label": "Batch Size", "type": "integer", "required": True, "min": 1, "max": 2048},
                {"key": "imgsz", "label": "Image Size", "type": "integer", "required": True, "min": 64, "max": 4096},
                {"key": "patience", "label": "Patience", "type": "integer", "required": False, "min": 1, "max": 1000},
                {"key": "topk", "label": "TopK", "type": "integer", "required": False, "min": 1, "max": 5000},
                {"key": "predict_conf", "label": "Predict Conf", "type": "number", "required": False, "min": 0.0, "max": 1.0},
                {"key": "val_split_ratio", "label": "Val Split Ratio", "type": "number", "required": False, "min": 0.05, "max": 0.5},
                {"key": "base_model", "label": "Base Model", "type": "string", "required": False},
                {"key": "device", "label": "Device", "type": "string", "required": False},
            ],
        }

    @property
    def default_request_config(self) -> dict[str, Any]:
        return {
            "epochs": 30,
            "batch": 16,
            "imgsz": 640,
            "patience": 20,
            "topk": 200,
            "predict_conf": 0.1,
            "val_split_ratio": 0.2,
            "base_model": "yolov8n-obb.pt",
            "device": "auto",
        }

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

    def _resolve_device(self, params: dict[str, Any]) -> tuple[Any, str, str]:
        requested_raw = params.get("device", "auto")
        requested = normalize_accelerator_name(requested_raw) or "auto"
        preferred_backend = normalize_accelerator_name(params.get("_resolved_device_backend"))

        available = available_accelerators(
            probe_hardware(
                cpu_workers=1,
                memory_mb=0,
            )
        )
        supported = {
            normalize_accelerator_name(item)
            for item in self.supported_accelerators
            if normalize_accelerator_name(item) and normalize_accelerator_name(item) != "auto"
        }
        supported = supported or {"cpu"}
        candidates = available & supported

        if requested != "auto":
            if requested == "cuda" and requested not in candidates:
                raise ValueError(
                    f"Invalid CUDA 'device={requested_raw}' requested. Use 'device=cpu' if no CUDA device is available."
                )
            if requested not in candidates:
                raise ValueError(
                    f"Requested device '{requested_raw}' is not available on this executor. "
                    f"available={sorted(available)} supported={sorted(supported)}"
                )
            params["_resolved_device_backend"] = requested
            if requested == "cuda":
                raw = str(requested_raw).strip()
                if raw and (raw.isdigit() or raw.startswith("cuda:") or "," in raw):
                    return requested_raw, str(requested_raw), requested
                return "0", str(requested_raw), requested
            if requested == "mps":
                return "mps", str(requested_raw), requested
            return "cpu", str(requested_raw), requested

        order = list(ACCELERATOR_PRIORITY)
        if preferred_backend in order:
            order = [preferred_backend] + [item for item in order if item != preferred_backend]
        resolved_backend = next((item for item in order if item in candidates), "")
        if not resolved_backend:
            raise ValueError(
                f"No available accelerator for auto mode. available={sorted(available)} supported={sorted(supported)}"
            )
        params["_resolved_device_backend"] = resolved_backend
        if resolved_backend == "cuda":
            return "0", str(requested_raw), resolved_backend
        if resolved_backend == "mps":
            return "mps", str(requested_raw), resolved_backend
        return "cpu", str(requested_raw), resolved_backend

    async def prepare_data(
        self,
        workspace: Workspace,
        labels: list[dict[str, Any]],
        samples: list[dict[str, Any]],
        annotations: list[dict[str, Any]],
        infer_image_hw: Callable[[Path], tuple[int, int]] | None = None,
        dataset_ir: Any | None = None,
    ) -> None:
        prepare_yolo_dataset(
            workspace=workspace,
            labels=labels,
            samples=samples,
            annotations=annotations,
            infer_image_hw=infer_image_hw or _infer_image_hw,
            to_int=_to_int,
            annotation_to_line=self._annotation_to_yolo_obb_line,
            resolve_split_config=self._resolve_split_config,
            dataset_ir=dataset_ir,
        )

    async def train(
        self,
        workspace: Workspace,
        params: dict[str, Any],
        emit: EventCallback,
    ) -> TrainOutput:
        self._stop_flag.clear()
        config = await resolve_train_config(
            workspace=workspace,
            params=params,
            to_int=_to_int,
            resolve_device=self._resolve_device,
            resolve_base_model=self._resolve_base_model,
        )
        train_result = await run_train_with_epoch_stream(
            workspace=workspace,
            config=config,
            emit=emit,
            run_train_sync=self._run_train_sync,
            to_int=_to_int,
        )
        prepare_stats = load_prepare_stats(workspace)
        metrics = normalize_training_metrics(
            metrics=dict(train_result["metrics"]),
            prepare_stats=prepare_stats,
            to_int=_to_int,
            to_bool=_to_bool,
        )
        report_path = self._write_training_report(
            workspace=workspace,
            metrics=metrics,
            train_result=train_result,
            prepare_stats=prepare_stats,
        )
        return self._build_train_output(
            metrics=metrics,
            train_result=train_result,
            report_path=report_path,
        )

    def _write_training_report(
        self,
        *,
        workspace: Workspace,
        metrics: dict[str, Any],
        train_result: dict[str, Any],
        prepare_stats: dict[str, Any],
    ) -> Path:
        report_path = workspace.artifacts_dir / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "metrics": metrics,
                    "history": train_result["history"],
                    "train_dir": str(train_result["save_dir"]),
                    "data_stats": prepare_stats,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return report_path

    def _build_train_output(
        self,
        *,
        metrics: dict[str, Any],
        train_result: dict[str, Any],
        report_path: Path,
    ) -> TrainOutput:
        best_path = Path(train_result["best_path"])
        extra_artifacts: list[TrainArtifact] = list(train_result.get("extra_artifacts", []))
        return TrainOutput(
            metrics=metrics,
            artifacts=[
                TrainArtifact(
                    kind="weights",
                    name="best.pt",
                    path=best_path,
                    content_type="application/octet-stream",
                    required=True,
                ),
                TrainArtifact(
                    kind="report",
                    name="report.json",
                    path=report_path,
                    content_type="application/json",
                    required=True,
                ),
                *extra_artifacts,
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
        random_seed = max(0, _to_int(params.get("random_seed", 0), 0))
        round_index = max(1, _to_int(params.get("round_index", 1), 1))
        device, _requested_device, _resolved_backend = self._resolve_device(params)

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
            random_seed=random_seed,
            round_index=round_index,
        )
        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return candidates[:topk]

    async def stop(self, step_id: str) -> None:
        del step_id
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
            required_fields = {"cx", "cy", "w", "h", "angle_deg", "normalized"}
            if not required_fields.issubset(obb.keys()):
                return None
            if not _to_bool(obb.get("normalized"), False):
                return None
            cx = _to_float(obb.get("cx"))
            cy = _to_float(obb.get("cy"))
            w = _to_float(obb.get("w"))
            h = _to_float(obb.get("h"))
            angle = _to_float(obb.get("angle_deg"), 0.0)
            if w <= 0 or h <= 0:
                return None
            corners = _rotated_rect_to_corners(
                cx * float(width),
                cy * float(height),
                w * float(width),
                h * float(height),
                angle,
            )

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

    async def _resolve_base_model(
        self,
        *,
        workspace: Workspace,
        base_model: str,
        params: dict[str, Any],
    ) -> str:
        base_model_download_url = str(params.get("base_model_download_url") or "").strip()
        if base_model_download_url:
            target = workspace.cache_dir / "warm_start_base_model.pt"
            await self._download_to_file(base_model_download_url, target)
            return str(target)

        if base_model.startswith("http://") or base_model.startswith("https://"):
            target = workspace.cache_dir / "remote_base_model.pt"
            await self._download_to_file(base_model, target)
            return str(target)

        if base_model.startswith("s3://"):
            raise RuntimeError("base_model uses s3 URI but base_model_download_url is missing")
        return base_model

    async def _download_to_file(self, url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)

    def _resolve_split_config(self, workspace: Workspace) -> tuple[int, float]:
        split_seed = 0
        val_ratio = 0.2
        payload: dict[str, Any] = {}
        if workspace.config_path.exists():
            try:
                payload = json.loads(workspace.config_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        split_seed = _to_int(params.get("split_seed"), 0)
        val_ratio = _clamp(_to_float(params.get("val_split_ratio", 0.2), 0.2), 0.05, 0.5)
        if split_seed <= 0:
            loop_id = str(payload.get("loop_id") or "")
            round_index = _to_int(payload.get("round_index"), 1)
            digest = hashlib.sha256(f"{loop_id}:{round_index}".encode("utf-8")).hexdigest()
            split_seed = int(digest[:8], 16)
        return split_seed, val_ratio

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
        epoch_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return run_train_sync(
            workspace=workspace,
            dataset_yaml=dataset_yaml,
            base_model=base_model,
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            patience=patience,
            device=device,
            stop_flag=self._stop_flag,
            load_yolo=self._load_yolo,
            ensure_cjk_plot_font=self._ensure_cjk_plot_font,
            normalize_metrics=self._normalize_metrics,
            to_float=_to_float,
            to_int=_to_int,
            epoch_callback=epoch_callback,
        )

    def _ensure_cjk_plot_font(self) -> None:
        if self._font_setup_done:
            return
        with self._font_setup_lock:
            if self._font_setup_done:
                return
            try:
                import matplotlib  # type: ignore
                from matplotlib import font_manager  # type: ignore
            except Exception:
                self._font_setup_done = True
                return

            available_fonts = {str(item.name or "").strip() for item in font_manager.fontManager.ttflist}
            selected = next(
                (name for name in self._CJK_FONT_CANDIDATES if name in available_fonts),
                "",
            )
            if selected:
                sans_serif = [str(item) for item in matplotlib.rcParams.get("font.sans-serif", [])]
                merged = [selected, *[item for item in sans_serif if item != selected]]
                matplotlib.rcParams["font.family"] = ["sans-serif"]
                matplotlib.rcParams["font.sans-serif"] = merged
                matplotlib.rcParams["axes.unicode_minus"] = False
            else:
                warnings.warn(
                    "No CJK font found for matplotlib plots. Install one of: "
                    + ", ".join(self._CJK_FONT_CANDIDATES),
                    RuntimeWarning,
                    stacklevel=2,
                )
            self._font_setup_done = True

    def _normalize_metrics(self, raw: dict[str, Any] | Any) -> dict[str, float]:
        return normalize_metrics_row(raw, _to_float)

    def _parse_results_csv(self, path: Path) -> list[dict[str, float]]:
        return parse_results_csv_rows(path, _to_float)

    def _pick_metric(self, row: dict[str, Any], keys: tuple[str, ...]) -> float:
        return pick_metric_value(row, keys, _to_float)

    def _score_unlabeled_sync(
        self,
        *,
        model_path: str,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        conf: float,
        imgsz: int,
        device: Any,
        random_seed: int,
        round_index: int,
    ) -> list[dict[str, Any]]:
        return score_unlabeled_samples(
            model_path=model_path,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            conf=conf,
            imgsz=imgsz,
            device=device,
            stop_flag=self._stop_flag,
            load_yolo=self._load_yolo,
            predict_with_aug=self._predict_with_aug,
            extract_predictions=self._extract_predictions,
            build_detection_boxes=build_detection_boxes,
            score_aug_iou_disagreement=score_aug_iou_disagreement,
            score_by_strategy=score_by_strategy,
            random_seed=random_seed,
            round_index=round_index,
        )

    def _predict_with_aug(
        self,
        *,
        model,
        image_path: Path,
        conf: float,
        imgsz: int,
        device: Any,
    ) -> list[list[dict[str, Any]]]:
        if Image is None or np is None:
            raise RuntimeError("numpy and pillow are required for yolo_det_v1 plugin")
        return predict_with_augmentations(
            model=model,
            image_path=image_path,
            conf=conf,
            imgsz=imgsz,
            device=device,
            ensure_image_deps=self._ensure_image_deps,
            image_cls=Image,
            np_mod=np,
            extract_predictions=self._extract_predictions,
            inverse_aug_box=self._inverse_aug_box,
        )

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
