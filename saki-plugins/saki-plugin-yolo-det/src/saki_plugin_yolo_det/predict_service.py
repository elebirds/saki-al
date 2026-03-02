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
from saki_plugin_sdk.strategies.aug_iou import build_detection_boxes, score_aug_iou_disagreement
from saki_plugin_sdk.strategies.builtin import normalize_strategy_name, score_by_strategy
from saki_plugin_yolo_det.common import clamp, to_float, to_int
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

        topk = max(1, to_int(cfg.topk if "topk" in cfg else cfg.sampling_topk if "sampling_topk" in cfg else 200), 200)
        conf = to_float(cfg.predict_conf, 0.1)
        imgsz = to_int(cfg.imgsz, 640)
        step_context = context.step_context
        random_seed = max(
            0,
            to_int(
                cfg.sampling_seed if "sampling_seed" in cfg else cfg.random_seed if "random_seed" in cfg else step_context.sampling_seed
            ),
            0,
        )
        round_index = max(1, to_int(cfg.round_index if "round_index" in cfg else step_context.round_index), 1)
        backend = str(context.device_binding.backend or "").strip().lower()
        device_spec = str(context.device_binding.device_spec or "").strip().lower()
        if backend == "cuda":
            device = device_spec.split(":", 1)[1] if device_spec.startswith("cuda:") else (device_spec or "0")
        elif backend == "mps":
            device = "mps"
        else:
            device = "cpu"

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

    def _ensure_image_deps(self) -> None:
        if Image is None or np is None:
            raise RuntimeError("numpy and pillow are required for yolo_det_v1 plugin")

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

        x1 = clamp(x1, 0.0, float(width))
        x2 = clamp(x2, 0.0, float(width))
        y1 = clamp(y1, 0.0, float(height))
        y2 = clamp(y2, 0.0, float(height))
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        return {
            "cls_id": int(row.get("cls_id", 0)),
            "conf": to_float(row.get("conf", 0.0), 0.0),
            "xyxy": [x1, y1, x2, y2],
        }
