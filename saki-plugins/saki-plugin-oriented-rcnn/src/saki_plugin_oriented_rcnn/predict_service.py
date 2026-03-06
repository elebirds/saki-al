from __future__ import annotations

import asyncio
import hashlib
import math
import threading
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from saki_plugin_sdk import ExecutionBindingContext, WorkspaceProtocol
from saki_plugin_sdk.strategies.builtin import normalize_strategy_name, score_by_strategy

from saki_plugin_oriented_rcnn.common import normalize_device, to_int
from saki_plugin_oriented_rcnn.config_builder import build_mmrotate_runtime_cfg, resolve_preset_checkpoint
from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.mmrotate_adapter import build_model, infer_source, infer_single_image
from saki_plugin_oriented_rcnn.prepare_pipeline import load_class_schema, load_prepare_manifest

try:  # pragma: no cover - 可选依赖
    from shapely.geometry import Polygon  # type: ignore
except Exception:  # pragma: no cover
    Polygon = None  # type: ignore


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
        cfg = self._config_service.resolve_config(params)

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
                conf_values = [float(item["confidence"]) for item in base_entries]
                max_conf = max(conf_values) if conf_values else 0.0
                score = float(1.0 - max(0.0, min(1.0, max_conf)))
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": score,
                        "reason": {
                            "strategy": "uncertainty_1_minus_max_conf",
                            "max_conf": float(max_conf),
                            "pred_count": len(base_entries),
                        },
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
                )
                score, reason = self._score_aug_iou_disagreement(preds_by_aug)
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": float(score),
                        "reason": {
                            "strategy": "aug_iou_disagreement",
                            **reason,
                        },
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
                score = _stable_random_score(
                    sample_id=sample_id,
                    random_seed=random_seed,
                )
                rows.append(
                    {
                        "sample_id": sample_id,
                        "score": score,
                        "reason": {
                            "strategy": "random_baseline",
                            "random_seed": int(random_seed),
                            "rand": float(score),
                        },
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
    ) -> list[list[dict[str, Any]]]:
        """生成多视角预测并映射回原图坐标系。

        设计意图：
        1. 主动学习里关注的是“同一张图在不同扰动下是否稳定”，
           所以所有增强分支都必须回到原图坐标，才能做可比的 IoU 计算。
        2. 亮度增强只改变像素，不改变几何；翻转增强需要做逆变换。
        """
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            base_img = np.array(rgb)

        h, w = base_img.shape[:2]

        # 增强集合保持“轻量且可解释”：
        # - identity 作为锚点分支
        # - hflip / vflip 检验几何鲁棒性
        # - bright 检验外观扰动鲁棒性
        transforms: list[tuple[str, Any]] = [
            ("identity", lambda arr: arr),
            ("hflip", lambda arr: np.ascontiguousarray(arr[:, ::-1, :])),
            ("vflip", lambda arr: np.ascontiguousarray(arr[::-1, :, :])),
            ("bright", lambda arr: np.clip(arr.astype(np.float32) * 1.2, 0, 255).astype(np.uint8)),
        ]

        outputs: list[list[dict[str, Any]]] = []
        for name, fn in transforms:
            aug = fn(base_img)
            pred = infer_source(model=model, source=aug)
            rows = self._build_entries(
                pred=pred,
                classes=classes,
                geometry_mode=geometry_mode,
                score_thr=score_thr,
                max_per_img=max_per_img,
            )
            restored: list[dict[str, Any]] = []
            for item in rows:
                qbox = tuple(float(v) for v in item.get("qbox", ()))
                qbox_inv = _inverse_qbox(name=name, qbox=qbox, width=w, height=h)
                restored.append(
                    {
                        **item,
                        "qbox": qbox_inv,
                        # 几何输出保持原模式，但 aug_iou 打分统一基于 qbox。
                        "geometry": _geometry_from_qbox_or_keep(
                            qbox=qbox_inv,
                            rbox=item.get("rbox"),
                            geometry_mode=geometry_mode,
                        ),
                    }
                )
            outputs.append(restored)

        return outputs

    def _score_aug_iou_disagreement(self, preds_by_aug: list[list[dict[str, Any]]]) -> tuple[float, dict[str, float]]:
        """计算 `aug_iou_disagreement` 分数。

        综合四个信号并裁剪到 [0,1]：
        - mean_iou: 同类匹配框的平均 IoU（越低表示增强后越不一致）
        - count_gap: 预测数量差异
        - class_gap: 类别分布差异
        - conf_std: 增强分支间平均置信度标准差
        """
        if not preds_by_aug:
            return 0.0, {
                "mean_iou": 1.0,
                "count_gap": 0.0,
                "class_gap": 0.0,
                "conf_std": 0.0,
                "score": 0.0,
            }
        if len(preds_by_aug) == 1:
            conf_mean = _safe_div(sum(float(v.get("confidence") or 0.0) for v in preds_by_aug[0]), len(preds_by_aug[0]))
            score = max(0.0, min(1.0, 0.15 * conf_mean))
            return score, {
                "mean_iou": 1.0,
                "count_gap": 0.0,
                "class_gap": 0.0,
                "conf_std": 0.0,
                "score": score,
            }

        anchor = preds_by_aug[0]
        others = preds_by_aug[1:]

        mean_iou_rows: list[float] = []
        count_gap_rows: list[float] = []
        class_gap_rows: list[float] = []

        for other in others:
            mean_iou_rows.append(self._pair_mean_iou_by_class(anchor, other))
            count_gap_rows.append(_safe_div(abs(len(anchor) - len(other)), max(1, max(len(anchor), len(other)))))
            class_gap_rows.append(self._class_hist_gap(anchor, other))

        mean_iou = _safe_div(sum(mean_iou_rows), len(mean_iou_rows))
        count_gap = _safe_div(sum(count_gap_rows), len(count_gap_rows))
        class_gap = _safe_div(sum(class_gap_rows), len(class_gap_rows))

        conf_means = [
            _safe_div(sum(float(v.get("confidence") or 0.0) for v in rows), len(rows))
            for rows in preds_by_aug
        ]
        mean_conf = _safe_div(sum(conf_means), len(conf_means))
        conf_var = _safe_div(sum((x - mean_conf) ** 2 for x in conf_means), len(conf_means))
        conf_std = max(0.0, min(1.0, math.sqrt(max(0.0, conf_var))))

        score = (
            0.45 * (1.0 - max(0.0, min(1.0, mean_iou)))
            + 0.2 * max(0.0, min(1.0, count_gap))
            + 0.2 * max(0.0, min(1.0, class_gap))
            + 0.15 * conf_std
        )
        score = max(0.0, min(1.0, score))

        return score, {
            "mean_iou": float(max(0.0, min(1.0, mean_iou))),
            "count_gap": float(max(0.0, min(1.0, count_gap))),
            "class_gap": float(max(0.0, min(1.0, class_gap))),
            "conf_std": float(conf_std),
            "score": float(score),
        }

    def _pair_mean_iou_by_class(self, left: list[dict[str, Any]], right: list[dict[str, Any]]) -> float:
        """按类计算两组预测的平均 IoU。

        对每个类别分别构造 IoU 矩阵并做最大权匹配，避免“多框对一框”的重复计分。
        """
        classes = {int(item.get("class_index", -1)) for item in left} | {int(item.get("class_index", -1)) for item in right}
        if not classes:
            return 1.0

        cls_iou: list[float] = []
        for cls_idx in classes:
            left_rows = [item for item in left if int(item.get("class_index", -1)) == cls_idx]
            right_rows = [item for item in right if int(item.get("class_index", -1)) == cls_idx]
            if not left_rows and not right_rows:
                continue
            if not left_rows or not right_rows:
                cls_iou.append(0.0)
                continue

            matrix = [[_polygon_iou(a.get("qbox", ()), b.get("qbox", ())) for b in right_rows] for a in left_rows]
            pairs = _hungarian_maximize(matrix)
            if not pairs:
                cls_iou.append(0.0)
                continue
            values = [matrix[i][j] for i, j in pairs]
            cls_iou.append(_safe_div(sum(values), len(values)))

        if not cls_iou:
            return 1.0
        return max(0.0, min(1.0, _safe_div(sum(cls_iou), len(cls_iou))))

    @staticmethod
    def _class_hist_gap(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> float:
        """类别直方图距离，结果归一化到 [0,1]。"""
        classes = {int(item.get("class_index", -1)) for item in left} | {int(item.get("class_index", -1)) for item in right}
        if not classes:
            return 0.0
        total_left = len(left)
        total_right = len(right)
        if total_left == 0 and total_right == 0:
            return 0.0

        gap = 0.0
        for cls_idx in classes:
            pa = _safe_div(sum(1 for x in left if int(x.get("class_index", -1)) == cls_idx), total_left)
            pb = _safe_div(sum(1 for x in right if int(x.get("class_index", -1)) == cls_idx), total_right)
            gap += abs(pa - pb)
        return max(0.0, min(1.0, gap * 0.5))

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


def _stable_random_score(*, sample_id: str, random_seed: int) -> float:
    digest = hashlib.sha256(f"{random_seed}:{sample_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / float(0xFFFFFFFF)


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

    x, y, rw, rh = _rect_from_qbox(qbox)
    return {
        "rect": {
            "x": float(x),
            "y": float(y),
            "width": float(rw),
            "height": float(rh),
        }
    }


def _geometry_from_qbox_or_keep(
    *,
    qbox: tuple[float, ...],
    rbox: Any,
    geometry_mode: str,
) -> dict[str, Any]:
    if isinstance(rbox, (list, tuple)) and len(rbox) >= 5:
        return _rbox_to_geometry(
            rbox=(float(rbox[0]), float(rbox[1]), float(rbox[2]), float(rbox[3]), float(rbox[4])),
            qbox=qbox,
            geometry_mode=geometry_mode,
        )
    x, y, w, h = _rect_from_qbox(qbox)
    return {
        "rect": {
            "x": float(x),
            "y": float(y),
            "width": float(w),
            "height": float(h),
        }
    }


def _inverse_qbox(*, name: str, qbox: tuple[float, ...], width: int, height: int) -> tuple[float, ...]:
    """把增强分支预测框逆变换回原图坐标。"""
    if len(qbox) != 8:
        return qbox
    pts = np.asarray(qbox, dtype=np.float32).reshape(4, 2)
    if name == "hflip":
        pts[:, 0] = float(width) - pts[:, 0]
    elif name == "vflip":
        pts[:, 1] = float(height) - pts[:, 1]
    return tuple(float(v) for v in pts.reshape(-1).tolist())


def _rect_from_qbox(qbox: tuple[float, ...]) -> tuple[float, float, float, float]:
    if len(qbox) != 8:
        return 0.0, 0.0, 0.0, 0.0
    pts = np.asarray(qbox, dtype=np.float32).reshape(4, 2)
    x0 = float(np.min(pts[:, 0]))
    y0 = float(np.min(pts[:, 1]))
    x1 = float(np.max(pts[:, 0]))
    y1 = float(np.max(pts[:, 1]))
    return x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _hungarian_maximize(weights: list[list[float]]) -> list[tuple[int, int]]:
    """匈牙利算法（最大化版本）。

    输入为权重矩阵，输出一组 `(row, col)` 匹配对，满足一对一约束，
    用于在两组预测框之间找到“总 IoU 最大”的对应关系。
    """
    if not weights or not weights[0]:
        return []

    rows = len(weights)
    cols = len(weights[0])
    n = max(rows, cols)

    max_weight = 0.0
    for row in weights:
        for value in row:
            if value > max_weight:
                max_weight = value

    # 标准匈牙利算法是“最小化代价”，这里把权重转成代价：
    # cost = max_weight - weight。
    inf_cost = max_weight + 1.0
    cost = [[inf_cost for _ in range(n)] for _ in range(n)]
    for i in range(rows):
        for j in range(cols):
            cost[i][j] = max_weight - weights[i][j]

    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment: list[tuple[int, int]] = []
    for j in range(1, n + 1):
        i = p[j]
        if i == 0:
            continue
        row_idx = i - 1
        col_idx = j - 1
        if row_idx < rows and col_idx < cols:
            assignment.append((row_idx, col_idx))
    return assignment


def _polygon_iou(left_qbox: Any, right_qbox: Any) -> float:
    """计算四边形 IoU。

    优先使用 shapely 精确多边形面积；若运行环境未安装 shapely，
    回退到外接 AABB IoU，保证流程可运行。
    """
    try:
        left = np.asarray(left_qbox, dtype=np.float32).reshape(4, 2)
        right = np.asarray(right_qbox, dtype=np.float32).reshape(4, 2)
    except Exception:
        return 0.0

    if Polygon is not None:
        try:
            p1 = Polygon([(float(x), float(y)) for x, y in left])
            p2 = Polygon([(float(x), float(y)) for x, y in right])
            if not p1.is_valid:
                p1 = p1.buffer(0)
            if not p2.is_valid:
                p2 = p2.buffer(0)
            if p1.is_empty or p2.is_empty:
                return 0.0
            inter = float(p1.intersection(p2).area)
            union = float(p1.union(p2).area)
            if union <= 0.0:
                return 0.0
            return max(0.0, min(1.0, inter / union))
        except Exception:
            pass

    # 无 shapely 时回退到外接轴对齐框 IoU。
    lx0, ly0 = float(np.min(left[:, 0])), float(np.min(left[:, 1]))
    lx1, ly1 = float(np.max(left[:, 0])), float(np.max(left[:, 1]))
    rx0, ry0 = float(np.min(right[:, 0])), float(np.min(right[:, 1]))
    rx1, ry1 = float(np.max(right[:, 0])), float(np.max(right[:, 1]))

    ix0, iy0 = max(lx0, rx0), max(ly0, ry0)
    ix1, iy1 = min(lx1, rx1), min(ly1, ry1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih

    la = max(0.0, lx1 - lx0) * max(0.0, ly1 - ly0)
    ra = max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0)
    union = la + ra - inter
    if union <= 0:
        return 0.0
    return max(0.0, min(1.0, inter / union))
