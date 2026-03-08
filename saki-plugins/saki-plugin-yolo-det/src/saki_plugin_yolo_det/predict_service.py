from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None  # type: ignore
try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

from saki_plugin_sdk import ExecutionBindingContext, WorkspaceProtocol
from saki_plugin_sdk.augmentations import build_augmented_views, inverse_augmented_prediction_row
from saki_plugin_sdk.strategies.builtin import normalize_strategy_name, score_by_strategy
from saki_ir import normalize_quad8, quad8_to_aabb_rect
from saki_plugin_yolo_det.common import to_float, to_int, to_yolo_device
from saki_plugin_yolo_det.config_service import YoloConfigService
from saki_plugin_yolo_det.predict_pipeline import predict_with_augmentations, score_unlabeled_samples


class YoloPredictService:
    def __init__(
        self,
        *,
        stop_flag: threading.Event,
        config_service: YoloConfigService,
        load_yolo: Callable[[], Any],
    ) -> None:
        self._stop_flag = stop_flag
        self._config_service = config_service
        self._load_yolo = load_yolo
        self._model_cache_lock = threading.Lock()
        self._cached_model_key: tuple[str, str] | None = None
        self._cached_model: Any | None = None

    async def predict_unlabeled(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        return await self.predict_unlabeled_batch(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def predict_unlabeled_batch(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        cfg = self._config_service.resolve_config(params)

        topk = max(1, to_int(getattr(cfg, "topk", getattr(cfg, "sampling_topk", 200)), 200))
        conf = to_float(cfg.predict_conf, 0.1)
        imgsz = to_int(cfg.imgsz, 640)
        task_context = context.task_context
        random_seed = max(
            0,
            to_int(
                getattr(cfg, "sampling_seed", getattr(cfg, "random_seed", task_context.sampling_seed))
            ),
            0,
        )
        round_index = max(1, to_int(getattr(cfg, "round_index", task_context.round_index)), 1)
        device = to_yolo_device(
            str(context.device_binding.backend or ""),
            str(context.device_binding.device_spec or ""),
        )

        best_path = workspace.artifacts_dir / "best.pt"
        fallback_model = await self._config_service.resolve_model_ref(workspace=workspace, params=cfg)
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

    async def predict_samples_batch(
        self,
        *,
        workspace: WorkspaceProtocol,
        samples: list[dict[str, Any]],
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        cfg = self._config_service.resolve_config(params)
        conf = to_float(cfg.predict_conf, 0.1)
        imgsz = to_int(cfg.imgsz, 640)
        device = to_yolo_device(
            str(context.device_binding.backend or ""),
            str(context.device_binding.device_spec or ""),
        )

        best_path = workspace.artifacts_dir / "best.pt"
        fallback_model = await self._config_service.resolve_model_ref(workspace=workspace, params=cfg)
        model_path = str(best_path if best_path.exists() else fallback_model)
        return await asyncio.to_thread(
            self._predict_samples_sync,
            model_path=model_path,
            samples=samples,
            conf=conf,
            imgsz=imgsz,
            device=device,
        )

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
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            conf=conf,
            imgsz=imgsz,
            device=device,
            stop_flag=self._stop_flag,
            get_model=lambda: self._get_or_load_model(model_path=model_path, device=device),
            predict_single_image=self._predict_single_image,
            predict_with_aug=self._predict_with_aug,
            extract_predictions=self._extract_predictions,
            score_by_strategy=score_by_strategy,
            normalize_strategy_name=normalize_strategy_name,
            random_seed=random_seed,
            round_index=round_index,
        )

    def _predict_samples_sync(
        self,
        *,
        model_path: str,
        samples: list[dict[str, Any]],
        conf: float,
        imgsz: int,
        device: Any,
    ) -> list[dict[str, Any]]:
        model = self._get_or_load_model(model_path=model_path, device=device)
        rows: list[dict[str, Any]] = []
        for sample in samples:
            if self._stop_flag.is_set():
                raise RuntimeError("prediction stopped")
            sample_id = str(sample.get("id") or "")
            local_path = str(sample.get("local_path") or "")
            if not sample_id or not local_path:
                continue
            image_path = Path(local_path)
            if not image_path.exists():
                continue
            predictions = self._predict_single_image(
                model=model,
                image_path=image_path,
                conf=conf,
                imgsz=imgsz,
                device=device,
            )
            max_conf = max((float(item.get("confidence") or 0.0) for item in predictions), default=0.0)
            rows.append(
                {
                    "sample_id": sample_id,
                    "score": float(max_conf),
                    "reason": {
                        "mode": "predict",
                        "pred_count": len(predictions),
                        "max_conf": float(max_conf),
                    },
                    "prediction_snapshot": {
                        "pred_count": len(predictions),
                        "base_predictions": predictions[:30],
                    },
                }
            )
        return rows

    def _get_or_load_model(self, *, model_path: str, device: Any) -> Any:
        model_key = (str(model_path or "").strip(), str(device).strip().lower())
        with self._model_cache_lock:
            if self._cached_model_key == model_key and self._cached_model is not None:
                return self._cached_model
            yolo_cls = self._load_yolo()
            model = yolo_cls(model_path)
            self._cached_model_key = model_key
            self._cached_model = model
            return model

    def _ensure_image_deps(self) -> None:
        if Image is None or np is None:
            raise RuntimeError("numpy and pillow are required for yolo_det_v1 plugin")

    def _load_predict_source(self, image_path: Path) -> Any:
        self._ensure_image_deps()
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            return np.array(rgb)  # type: ignore[union-attr]

    def _predict_single_image(
        self,
        *,
        model: Any,
        image_path: Path,
        conf: float,
        imgsz: int,
        device: Any,
    ) -> list[dict[str, Any]]:
        source = self._load_predict_source(image_path)
        predicts = model.predict(
            source=source,
            conf=conf,
            imgsz=imgsz,
            device=device,
            verbose=False,
        )
        first = predicts[0] if predicts else None
        return self._extract_predictions(first)

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
        )

    def _extract_predictions(self, result) -> list[dict[str, Any]]:
        if result is None:
            return []

        names_raw = getattr(result, "names", None)

        def _class_name_for(cls_idx: int) -> str:
            if isinstance(names_raw, dict):
                return str(names_raw.get(int(cls_idx)) or "")
            if isinstance(names_raw, list) and 0 <= int(cls_idx) < len(names_raw):
                return str(names_raw[int(cls_idx)] or "")
            return ""

        rows: list[dict[str, Any]] = []
        obb = getattr(result, "obb", None)
        if obb is not None and len(obb) > 0:
            cls_values = obb.cls.cpu().tolist()
            conf_values = obb.conf.cpu().tolist()
            if hasattr(obb, "xyxyxyxy"):
                qbox_values = obb.xyxyxyxy.cpu().tolist()
                for cls_id, conf, raw_qbox in zip(cls_values, conf_values, qbox_values):
                    qbox = normalize_quad8(raw_qbox)
                    if qbox is None:
                        continue
                    cls_idx = int(cls_id)
                    x, y, width, height = quad8_to_aabb_rect(qbox)
                    rows.append(
                        {
                            "class_index": cls_idx,
                            "class_name": _class_name_for(cls_idx),
                            "confidence": float(conf),
                            "qbox": qbox,
                            "geometry": {
                                "rect": {
                                    "x": x,
                                    "y": y,
                                    "width": width,
                                    "height": height,
                                }
                            },
                        }
                    )
                return rows

            if hasattr(obb, "xyxy"):
                xyxy_values = obb.xyxy.cpu().tolist()
                for cls_id, conf, xyxy in zip(cls_values, conf_values, xyxy_values):
                    cls_idx = int(cls_id)
                    x1, y1, x2, y2 = [float(v) for v in xyxy[:4]]
                    x = min(x1, x2)
                    y = min(y1, y2)
                    width = abs(x2 - x1)
                    height = abs(y2 - y1)
                    rows.append(
                        {
                            "class_index": cls_idx,
                            "class_name": _class_name_for(cls_idx),
                            "confidence": float(conf),
                            "geometry": {
                                "rect": {
                                    "x": x,
                                    "y": y,
                                    "width": width,
                                    "height": height,
                                }
                            },
                        }
                    )
                return rows

        boxes = getattr(result, "boxes", None)
        if boxes is not None and len(boxes) > 0:
            cls_values = boxes.cls.cpu().tolist()
            conf_values = boxes.conf.cpu().tolist()
            xyxy_values = boxes.xyxy.cpu().tolist()
            for cls_id, conf, xyxy in zip(cls_values, conf_values, xyxy_values):
                cls_idx = int(cls_id)
                x1, y1, x2, y2 = [float(v) for v in xyxy[:4]]
                x = min(x1, x2)
                y = min(y1, y2)
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                rows.append(
                    {
                        "class_index": cls_idx,
                        "class_name": _class_name_for(cls_idx),
                        "confidence": float(conf),
                        "geometry": {
                            "rect": {
                                "x": x,
                                "y": y,
                                "width": width,
                                "height": height,
                            }
                        },
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
        if Image is None or np is None:
            raise RuntimeError("numpy and pillow are required for yolo_det_v1 plugin")
        h = max(1, to_int(height, 1))
        w = max(1, to_int(width, 1))
        dummy = np.zeros((h, w, 3), dtype=np.uint8)
        views = build_augmented_views(dummy, np_mod=np, image_cls=Image)
        key = str(name or "").strip().lower()
        view = next((item for item in views if item.name == key), views[0])
        out = inverse_augmented_prediction_row(row, view=view)
        out["confidence"] = to_float(out.get("confidence", 0.0), 0.0)
        return out
