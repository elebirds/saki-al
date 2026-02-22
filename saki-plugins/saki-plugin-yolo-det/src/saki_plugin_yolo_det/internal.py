from __future__ import annotations

import asyncio
import hashlib
import json
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

from saki_plugin_sdk import Workspace, TrainArtifact, TrainOutput
from saki_plugin_sdk.base import EventCallback
from saki_plugin_sdk.manifest import PluginManifest
from saki_plugin_yolo_det.hardware import (
    available_accelerators,
    normalize_accelerator_name,
    probe_hardware,
)
from saki_plugin_yolo_det.prepare_pipeline import prepare_yolo_dataset
from saki_plugin_yolo_det.metrics_parser import (
    normalize_metrics as normalize_metrics_row,
    parse_results_csv as parse_results_csv_rows,
    pick_metric as pick_metric_value,
)
from saki_plugin_yolo_det.predict_pipeline import (
    predict_with_augmentations,
    score_unlabeled_samples,
)
from saki_plugin_yolo_det.train_async import (
    load_prepare_stats,
    normalize_training_metrics,
    resolve_train_config,
    run_train_with_epoch_stream,
)
from saki_plugin_yolo_det.train_sync_runner import run_train_sync
from saki_plugin_sdk.strategies.aug_iou import (
    build_detection_boxes,
    score_aug_iou_disagreement,
)
from saki_plugin_sdk.strategies.builtin import normalize_strategy_name, score_by_strategy


# ---------------------------------------------------------------------------
# Utility helpers (inlined to avoid coupling to executor internals)
# ---------------------------------------------------------------------------

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
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


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
    _MODEL_PRESETS = (
        "yolov8n-obb.pt",
        "yolov8s-obb.pt",
        "yolov8m-obb.pt",
        "yolov8l-obb.pt",
        "yolov8x-obb.pt",
    )
    _DETECT_PRESETS = (
        "yolov8n.pt",
        "yolov8s.pt",
        "yolov8m.pt",
        "yolov8l.pt",
        "yolov8x.pt",
    )
    _OBB_PRESETS = (
        "yolov8n-obb.pt",
        "yolov8s-obb.pt",
        "yolov8m-obb.pt",
        "yolov8l-obb.pt",
        "yolov8x-obb.pt",
    )
    _VALID_YOLO_TASKS = ("detect", "obb")

    def __init__(self) -> None:
        self._stop_flag = threading.Event()
        self._font_setup_lock = threading.Lock()
        self._font_setup_done = False
        self._manifest = PluginManifest.from_yaml(
            Path(__file__).resolve().parents[2] / "plugin.yml"
        )

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @property
    def plugin_id(self) -> str:
        return "yolo_det_v1"

    @property
    def version(self) -> str:
        return "0.2.0"

    @property
    def display_name(self) -> str:
        return "YOLO Detection"

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
            "aug_iou_disagreement",
            "uncertainty_1_minus_max_conf",
            "random_baseline",
        ]

    @property
    def supported_accelerators(self) -> list[str]:
        return ["cuda", "mps", "cpu"]

    @property
    def supports_auto_fallback(self) -> bool:
        return True

    def _presets_for_task(self, yolo_task: str) -> tuple[str, ...]:
        """Return the model preset tuple for a given yolo_task."""
        if yolo_task == "detect":
            return self._DETECT_PRESETS
        return self._OBB_PRESETS

    def resolve_config(self, mode: str, raw_config: dict[str, Any] | None) -> "PluginConfig":
        from saki_plugin_sdk.config import PluginConfig

        # SDK handles: merge defaults, resolve cond, coerce types, schema validation
        config = PluginConfig.from_manifest(
            self._manifest,
            raw_config if isinstance(raw_config, dict) else None,
            validate=True,
        )

        # --- plugin-specific cross-field validation ---
        yolo_task = str(config.yolo_task).strip().lower()
        if yolo_task not in self._VALID_YOLO_TASKS:
            raise ValueError(f"unsupported yolo_task: {yolo_task!r}, must be one of {self._VALID_YOLO_TASKS}")
        allowed_presets = self._presets_for_task(yolo_task)

        source = str(config.model_source).strip().lower()
        preset = str(config.get("model_preset") or allowed_presets[0]).strip()
        if preset not in allowed_presets:
            if preset in self._DETECT_PRESETS or preset in self._OBB_PRESETS:
                preset = allowed_presets[0]
            else:
                raise ValueError(f"unsupported model_preset: {preset or '<empty>'} for yolo_task={yolo_task}")

        custom_ref = str(config.get("model_custom_ref") or "").strip()
        if source != "preset" and not custom_ref:
            raise ValueError("model_custom_ref is required for custom model source")

        return config.with_updates(
            yolo_task=yolo_task,
            model_source=source,
            model_preset=preset,
            model_custom_ref="" if source == "preset" else custom_ref,
        )

    def validate_params(self, params: dict[str, Any]) -> None:
        self.resolve_config(mode="manual", raw_config=params)

    def _resolve_device(self, params: Any) -> tuple[Any, str, str]:
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
            if requested == "cuda":
                raw = str(requested_raw).strip()
                if raw and (raw.isdigit() or raw.startswith("cuda:") or "," in raw):
                    return requested_raw, str(requested_raw), requested
                return "0", str(requested_raw), requested
            if requested == "mps":
                return "mps", str(requested_raw), requested
            return "cpu", str(requested_raw), requested

        # MPS may hit unstable accelerator indexing errors on some OBB training workloads.
        # For auto mode we prefer cpu over mps unless user explicitly requests mps.
        order = ["cuda", "cpu", "mps"]
        if preferred_backend in order and preferred_backend != "mps":
            order = [preferred_backend] + [item for item in order if item != preferred_backend]
        resolved_backend = next((item for item in order if item in candidates), "")
        if not resolved_backend:
            raise ValueError(
                f"No available accelerator for auto mode. available={sorted(available)} supported={sorted(supported)}"
            )
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
        dataset_ir: Any,
        infer_image_hw: Callable[[Path], tuple[int, int]] | None = None,
        splits: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        del annotations
        # Extract yolo_task from splits if injected by runner
        yolo_task = "obb"
        if isinstance(splits, dict) and "yolo_task" in splits:
            yolo_task = str(splits.pop("yolo_task"))
        prepare_yolo_dataset(
            workspace=workspace,
            labels=labels,
            samples=samples,
            infer_image_hw=infer_image_hw or _infer_image_hw,
            to_int=_to_int,
            dataset_ir=dataset_ir,
            splits=splits,
            yolo_task=yolo_task,
        )

    async def train(
        self,
        workspace: Workspace,
        params: dict[str, Any],
        emit: EventCallback,
    ) -> TrainOutput:
        self._stop_flag.clear()
        resolved_params = self.resolve_config(mode="manual", raw_config=params)
        config = await resolve_train_config(
            workspace=workspace,
            plugin_config=resolved_params,
            resolve_device=self._resolve_device,
            resolve_model_ref=self._resolve_model_ref,
        )
        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"training reproducibility train_seed={config.train_seed} "
                    f"deterministic={config.deterministic} split_seed={resolved_params.get('split_seed', 0)}"
                ),
            },
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
        cfg = self.resolve_config(mode="manual", raw_config=params)
        topk = max(1, _to_int(cfg.get("topk", cfg.get("sampling_topk", 200)), 200))
        conf = _to_float(cfg.get("predict_conf", 0.1), 0.1)
        imgsz = _to_int(cfg.get("imgsz", 640), 640)
        random_seed = max(0, _to_int(cfg.get("sampling_seed", cfg.get("random_seed", 0)), 0))
        round_index = max(1, _to_int(cfg.get("round_index", 1), 1))
        device, _requested_device, _resolved_backend = self._resolve_device(cfg)

        best_path = workspace.artifacts_dir / "best.pt"
        fallback_model = await self._resolve_model_ref(workspace=workspace, params=cfg)
        model_path = str(best_path if best_path.exists() else fallback_model)

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

    async def _resolve_model_ref(
        self,
        *,
        workspace: Workspace,
        params: Any,
    ) -> str:
        source = str(params.get("model_source") or "preset").strip().lower()
        yolo_task = str(params.get("yolo_task") or "obb").strip().lower()
        allowed_presets = self._presets_for_task(yolo_task)

        if source == "preset":
            preset = str(params.get("model_preset") or "").strip()
            if not preset or preset not in allowed_presets:
                preset = allowed_presets[0]
            return preset

        custom_ref = str(params.get("model_custom_ref") or "").strip()
        if not custom_ref:
            raise RuntimeError("model_custom_ref is required")

        if source == "custom_local":
            local_path = Path(custom_ref).expanduser()
            if not local_path.exists():
                raise RuntimeError(f"custom local model not found: {local_path}")
            return str(local_path)

        if source == "custom_url":
            cache_key = hashlib.sha256(custom_ref.encode("utf-8")).hexdigest()
            target = workspace.cache_dir / "model_refs" / f"{cache_key}.pt"
            if not target.exists():
                await self._download_to_file(custom_ref, target)
            return str(target)

        raise RuntimeError(f"unsupported model_source: {source or '<empty>'}")

    async def _download_to_file(self, url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)

    def _load_yolo(self):
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "ultralytics is required for yolo_det_v1 plugin, please install it in the plugin environment"
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
        train_seed: int,
        deterministic: bool,
        yolo_task: str = "obb",
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
            train_seed=train_seed,
            deterministic=deterministic,
            stop_flag=self._stop_flag,
            load_yolo=self._load_yolo,
            ensure_cjk_plot_font=self._ensure_cjk_plot_font,
            normalize_metrics=self._normalize_metrics,
            to_float=_to_float,
            to_int=_to_int,
            yolo_task=yolo_task,
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
            normalize_strategy_name=normalize_strategy_name,
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
