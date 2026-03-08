from __future__ import annotations

import asyncio
import math
import threading
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from saki_plugin_sdk import ExecutionBindingContext, WorkspaceProtocol
from saki_plugin_sdk.augmentations import build_augmented_views, inverse_augmented_prediction_row
from saki_plugin_sdk.strategies.builtin import normalize_strategy_name, score_by_strategy
from saki_ir import normalize_quad8, quad8_to_aabb_rect, quad8_to_obb_payload

from saki_plugin_oriented_rcnn.common import normalize_device, to_int
from saki_plugin_oriented_rcnn.config_builder import build_mmrotate_runtime_cfg, resolve_preset_checkpoint
from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.mmrotate_adapter import build_model, infer_source, infer_single_image
from saki_plugin_oriented_rcnn.prepare_pipeline import load_class_schema, load_prepare_manifest


class OrientedRCNNPredictService:
    """未标注样本预测与主动学习打分服务。"""

    def __init__(
        self,
        *,
        stop_flag: threading.Event,
        config_service: OrientedRCNNConfigService,
    ) -> None:
        self._stop_flag = stop_flag
        self._config_service = config_service
        self._model_cache_lock = threading.Lock()
        self._cached_model_key: tuple[str, str, str] | None = None
        self._cached_model: Any | None = None

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
        cfg = self._config_service.resolve_config(params, strategy=strategy)

        schema = load_class_schema(workspace)
        classes = tuple(str(v) for v in (schema.get("classes") or []) if str(v).strip())
        if not classes:
            # score/predict 在部分流程下会复用缓存数据；
            # 若 class_schema 仍不可用，至少提供一个兜底类，保证流程不中断。
            classes = ("object",)

        manifest = load_prepare_manifest(workspace)
        device = normalize_device(
            backend=str(context.device_binding.backend or ""),
            device_spec=str(context.device_binding.device_spec or ""),
        )

        model_ref = await self._config_service.resolve_best_or_fallback_model(workspace=workspace, config=cfg)
        checkpoint_ref = _resolve_model_checkpoint_ref(model_ref)

        runtime_cfg_path = workspace.cache_dir / "mmrotate_predict_runtime.py"
        work_dir = workspace.root / "mmrotate_workdir" / "predict"
        work_dir.mkdir(parents=True, exist_ok=True)

        build_mmrotate_runtime_cfg(
            output_path=runtime_cfg_path,
            data_root=workspace.data_dir,
            classes=classes,
            epochs=max(1, cfg.epochs),
            batch=max(1, cfg.batch),
            workers=cfg.workers,
            imgsz=cfg.imgsz,
            nms_iou_thr=cfg.nms_iou_thr,
            max_per_img=cfg.max_per_img,
            val_degraded=bool(manifest.get("val_degraded", True)),
            work_dir=work_dir,
            load_from=checkpoint_ref,
            train_seed=int(cfg.train_seed or context.task_context.train_seed),
            train_sample_count=int(manifest.get("train_sample_count") or 0),
        )

        topk = max(1, to_int(params.get("sampling_topk", params.get("topk", 200)), 200))
        random_seed = int(cfg.sampling_seed or context.task_context.sampling_seed)
        round_index = int(cfg.round_index or context.task_context.round_index)
        geometry_mode = self._resolve_geometry_mode(cfg)

        model = await asyncio.to_thread(
            self._get_or_load_model,
            config_path=str(runtime_cfg_path),
            checkpoint_ref=checkpoint_ref,
            device=device,
        )

        candidates = await asyncio.to_thread(
            self._score_samples_sync,
            model=model,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            classes=classes,
            geometry_mode=geometry_mode,
            score_thr=float(cfg.predict_conf),
            max_per_img=int(cfg.max_per_img),
            random_seed=random_seed,
            round_index=round_index,
            aug_enabled_names=tuple(cfg.aug_iou_enabled_augs),
        )

        candidates.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
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

        schema = load_class_schema(workspace)
        classes = tuple(str(v) for v in (schema.get("classes") or []) if str(v).strip())
        if not classes:
            classes = ("object",)

        manifest = load_prepare_manifest(workspace)
        device = normalize_device(
            backend=str(context.device_binding.backend or ""),
            device_spec=str(context.device_binding.device_spec or ""),
        )

        model_ref = await self._config_service.resolve_best_or_fallback_model(workspace=workspace, config=cfg)
        checkpoint_ref = _resolve_model_checkpoint_ref(model_ref)

        runtime_cfg_path = workspace.cache_dir / "mmrotate_predict_runtime.py"
        work_dir = workspace.root / "mmrotate_workdir" / "predict"
        work_dir.mkdir(parents=True, exist_ok=True)

        build_mmrotate_runtime_cfg(
            output_path=runtime_cfg_path,
            data_root=workspace.data_dir,
            classes=classes,
            epochs=max(1, cfg.epochs),
            batch=max(1, cfg.batch),
            workers=cfg.workers,
            imgsz=cfg.imgsz,
            nms_iou_thr=cfg.nms_iou_thr,
            max_per_img=cfg.max_per_img,
            val_degraded=bool(manifest.get("val_degraded", True)),
            work_dir=work_dir,
            load_from=checkpoint_ref,
            train_seed=int(cfg.train_seed or context.task_context.train_seed),
            train_sample_count=int(manifest.get("train_sample_count") or 0),
        )

        geometry_mode = self._resolve_geometry_mode(cfg)
        model = await asyncio.to_thread(
            self._get_or_load_model,
            config_path=str(runtime_cfg_path),
            checkpoint_ref=checkpoint_ref,
            device=device,
        )
        return await asyncio.to_thread(
            self._predict_samples_sync,
            model=model,
            samples=samples,
            classes=classes,
            geometry_mode=geometry_mode,
            score_thr=float(cfg.predict_conf),
            max_per_img=int(cfg.max_per_img),
        )

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

    def _predict_samples_sync(
        self,
        *,
        model: Any,
        samples: list[dict[str, Any]],
        classes: tuple[str, ...],
        geometry_mode: str,
        score_thr: float,
        max_per_img: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sample in samples:
            if self._stop_flag.is_set():
                raise RuntimeError("prediction stopped")

            sample_id = str(sample.get("id") or "").strip()
            local_path = str(sample.get("local_path") or "").strip()
            if not sample_id or not local_path:
                continue
            image_path = Path(local_path)
            if not image_path.exists():
                continue

            base_pred = infer_single_image(model=model, image_path=image_path)
            base_entries = self._build_entries(
                pred=base_pred,
                classes=classes,
                geometry_mode=geometry_mode,
                score_thr=score_thr,
                max_per_img=max_per_img,
            )
            max_conf = max((float(item["confidence"]) for item in base_entries), default=0.0)
            rows.append(
                {
                    "sample_id": sample_id,
                    "score": float(max_conf),
                    "reason": {
                        "mode": "predict",
                        "pred_count": len(base_entries),
                        "max_conf": float(max_conf),
                    },
                    "prediction_snapshot": {
                        "pred_count": len(base_entries),
                        "base_predictions": [self._export_entry(item) for item in base_entries[:30]],
                    },
                }
            )
        return rows

    def _get_or_load_model(
        self,
        *,
        config_path: str,
        checkpoint_ref: str,
        device: str,
    ) -> Any:
        key = (str(config_path), str(checkpoint_ref), str(device))
        with self._model_cache_lock:
            if self._cached_model_key == key and self._cached_model is not None:
                return self._cached_model
            model = build_model(
                config_path=Path(config_path),
                checkpoint=str(checkpoint_ref),
                device=str(device),
            )
            self._cached_model_key = key
            self._cached_model = model
            return model

    @staticmethod
    def _resolve_geometry_mode(cfg: Any) -> str:
        explicit = str(getattr(cfg, "predict_geometry_mode", "auto") or "auto").strip().lower()
        if explicit in {"obb", "rect"}:
            return explicit

        annotation_types = {
            str(v).strip().lower()
            for v in getattr(cfg, "annotation_types", ())
            if str(v).strip()
        }
        if "obb" in annotation_types:
            return "obb"
        return "rect"

    def _score_samples_sync(
        self,
        *,
        model: Any,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        classes: tuple[str, ...],
        geometry_mode: str,
        score_thr: float,
        max_per_img: int,
        random_seed: int,
        round_index: int,
        aug_enabled_names: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        strategy_key = normalize_strategy_name(strategy)
        rows: list[dict[str, Any]] = []

        for sample in unlabeled_samples:
            if self._stop_flag.is_set():
                raise RuntimeError("sampling stopped")

            sample_id = str(sample.get("id") or "").strip()
            local_path = str(sample.get("local_path") or "").strip()
            if not sample_id or not local_path:
                continue
            image_path = Path(local_path)
            if not image_path.exists():
                continue

            base_pred = infer_single_image(model=model, image_path=image_path)
            base_entries = self._build_entries(
                pred=base_pred,
                classes=classes,
                geometry_mode=geometry_mode,
                score_thr=score_thr,
                max_per_img=max_per_img,
            )

            if strategy_key == "uncertainty_1_minus_max_conf":
                score, reason = score_by_strategy(
                    strategy_key,
                    sample_id,
                    random_seed=random_seed,
                    round_index=round_index,
                    predictions=base_entries,
                )
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": float(score),
                        "reason": dict(reason or {}),
                        "prediction_snapshot": {
                            "strategy": "uncertainty_1_minus_max_conf",
                            "pred_count": len(base_entries),
                            "base_predictions": [self._export_entry(item) for item in base_entries[:30]],
                        },
                    }
                )
                continue

            if strategy_key == "aug_iou_disagreement":
                preds_by_aug = self._predict_with_augmentations(
                    model=model,
                    image_path=image_path,
                    classes=classes,
                    geometry_mode=geometry_mode,
                    score_thr=score_thr,
                    max_per_img=max_per_img,
                    enabled_aug_names=aug_enabled_names,
                )
                score, reason = score_by_strategy(
                    strategy_key,
                    sample_id,
                    random_seed=random_seed,
                    round_index=round_index,
                    predictions_by_aug=preds_by_aug,
                )
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": float(score),
                        "reason": dict(reason or {}),
                        "prediction_snapshot": {
                            "strategy": "aug_iou_disagreement",
                            "aug_count": len(preds_by_aug),
                            "pred_per_aug": [len(v) for v in preds_by_aug],
                            "base_predictions": [
                                self._export_entry(item)
                                for item in (preds_by_aug[0] if preds_by_aug else [])[:30]
                            ],
                        },
                    }
                )
                continue

            if strategy_key == "random_baseline":
                score, reason = score_by_strategy(
                    strategy_key,
                    sample_id,
                    random_seed=random_seed,
                    round_index=round_index,
                )
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": float(score),
                        "reason": dict(reason or {}),
                    }
                )
                continue

            # 对未知策略保留 SDK 兜底，确保扩展策略时不中断。
            score, reason = score_by_strategy(
                strategy_key,
                sample_id,
                random_seed=random_seed,
                round_index=round_index,
            )
            rows.append(
                {
                    "sample_id": sample_id,
                    "score": float(score),
                    "reason": dict(reason or {}),
                }
            )

        return rows

    def _build_entries(
        self,
        *,
        pred: dict[str, np.ndarray],
        classes: tuple[str, ...],
        geometry_mode: str,
        score_thr: float,
        max_per_img: int,
    ) -> list[dict[str, Any]]:
        labels = pred.get("labels", np.zeros((0,), dtype=np.int64))
        scores = pred.get("scores", np.zeros((0,), dtype=np.float32))
        rboxes = pred.get("rboxes", np.zeros((0, 5), dtype=np.float32))
        qboxes = pred.get("qboxes", np.zeros((0, 8), dtype=np.float32))

        total = min(len(labels), len(scores), len(rboxes), len(qboxes))
        entries: list[dict[str, Any]] = []
        for i in range(total):
            score = float(scores[i])
            if score < float(score_thr):
                continue

            cls_idx = int(labels[i])
            class_name = classes[cls_idx] if 0 <= cls_idx < len(classes) else f"class_{cls_idx}"

            rbox = tuple(float(v) for v in rboxes[i][:5])
            qbox = tuple(float(v) for v in qboxes[i][:8])

            geometry = _rbox_to_geometry(
                rbox=rbox,
                qbox=qbox,
                geometry_mode=geometry_mode,
            )
            entries.append(
                {
                    "class_index": cls_idx,
                    "class_name": str(class_name),
                    "confidence": float(max(0.0, min(1.0, score))),
                    "geometry": geometry,
                    "rbox": rbox,
                    "qbox": qbox,
                }
            )

        entries.sort(key=lambda row: float(row["confidence"]), reverse=True)
        return entries[: max(1, int(max_per_img))]

    def _predict_with_augmentations(
        self,
        *,
        model: Any,
        image_path: Path,
        classes: tuple[str, ...],
        geometry_mode: str,
        score_thr: float,
        max_per_img: int,
        enabled_aug_names: tuple[str, ...] | None = None,
    ) -> list[list[dict[str, Any]]]:
        """生成多视角预测并映射回原图坐标系。

        设计意图：
        1. 主动学习里关注的是“同一张图在不同扰动下是否稳定”，
           所以所有增强分支都必须回到原图坐标，才能做可比的 IoU 计算。
        2. 增强集合由 SDK 统一管理，插件仅负责推理编排。
        """
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            base_img = np.array(rgb)

        views = build_augmented_views(
            base_img,
            np_mod=np,
            image_cls=Image,
            enabled_names=enabled_aug_names,
        )

        outputs: list[list[dict[str, Any]]] = []
        for view in views:
            pred = infer_source(model=model, source=view.image)
            rows = self._build_entries(
                pred=pred,
                classes=classes,
                geometry_mode=geometry_mode,
                score_thr=score_thr,
                max_per_img=max_per_img,
            )
            restored: list[dict[str, Any]] = []
            for item in rows:
                restored_item = inverse_augmented_prediction_row(item, view=view)
                qbox_inv = normalize_quad8(restored_item.get("qbox"))
                if qbox_inv is not None:
                    restored_item["qbox"] = qbox_inv
                    restored_item["geometry"] = _geometry_from_qbox(
                        qbox=qbox_inv,
                        geometry_mode=geometry_mode,
                    )
                restored.append(restored_item)
            outputs.append(restored)

        return outputs

    @staticmethod
    def _export_entry(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "class_index": int(item.get("class_index", 0)),
            "class_name": str(item.get("class_name") or ""),
            "confidence": float(item.get("confidence") or 0.0),
            "geometry": dict(item.get("geometry") or {}),
        }


def _resolve_model_checkpoint_ref(model_ref: str) -> str:
    text = str(model_ref or "").strip()
    if not text:
        raise RuntimeError("model_ref is empty")
    if text in {"oriented-rcnn-le90_r50_fpn_1x_dota"}:
        return resolve_preset_checkpoint(text)
    return text


def _rbox_to_geometry(
    *,
    rbox: tuple[float, float, float, float, float],
    qbox: tuple[float, ...],
    geometry_mode: str,
) -> dict[str, Any]:
    cx, cy, w, h, angle_rad = rbox
    if geometry_mode == "obb":
        return {
            "obb": {
                "cx": float(cx),
                "cy": float(cy),
                "width": float(max(0.0, w)),
                "height": float(max(0.0, h)),
                "angle_deg_ccw": float(math.degrees(angle_rad)),
            }
        }

    try:
        x, y, rw, rh = quad8_to_aabb_rect(qbox)
    except Exception:
        x = y = rw = rh = 0.0
    return {
        "rect": {
            "x": float(x),
            "y": float(y),
            "width": float(rw),
            "height": float(rh),
        }
    }


def _geometry_from_qbox(
    *,
    qbox: tuple[float, ...],
    geometry_mode: str,
) -> dict[str, Any]:
    if geometry_mode == "obb":
        try:
            return quad8_to_obb_payload(qbox, fit_mode="strict_then_min_area")
        except Exception:
            pass
    try:
        x, y, w, h = quad8_to_aabb_rect(qbox)
    except Exception:
        x = y = w = h = 0.0
    return {
        "rect": {
            "x": float(x),
            "y": float(y),
            "width": float(w),
            "height": float(h),
        }
    }
