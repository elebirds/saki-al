from __future__ import annotations

from collections.abc import Mapping
from itertools import zip_longest
from pathlib import Path
from threading import Event
from typing import Any, Callable

from saki_plugin_sdk.augmentations import (
    AugmentationSpec,
    build_augmented_views,
    inverse_augmented_prediction_row,
)


def score_unlabeled_samples(
    *,
    unlabeled_samples: list[dict[str, Any]],
    strategy: str,
    conf: float,
    imgsz: int,
    device: Any,
    stop_flag: Event,
    get_model: Callable[[], Any] | None,
    predict_single_image: Callable[..., list[dict[str, Any]]],
    predict_with_aug: Callable[..., list[list[dict[str, Any]]]],
    extract_predictions: Callable[[Any], list[dict[str, Any]]],
    score_by_strategy: Callable[..., tuple[float, dict[str, Any]]],
    normalize_strategy_name: Callable[[str], str],
    random_seed: int,
    round_index: int,
    aug_enabled_names: tuple[str, ...] | list[str] | None = None,
    aug_iou_mode: str = "obb",
    aug_iou_boundary_d: int = 3,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, Any]]:
    strategy_key = normalize_strategy_name(strategy)
    need_model = strategy_key in {"aug_iou_disagreement", "uncertainty_1_minus_max_conf"}
    model = get_model() if need_model and callable(get_model) else None
    if need_model and model is None:
        raise RuntimeError(f"model is required for strategy={strategy_key}")
    candidates: list[dict[str, Any]] = []
    valid_total = sum(
        1
        for sample in unlabeled_samples
        if str(sample.get("id") or "").strip() and Path(str(sample.get("local_path") or "")).exists()
    )
    processed = 0

    for sample in unlabeled_samples:
        if stop_flag.is_set():
            raise RuntimeError("sampling stopped")
        sample_id = str(sample.get("id") or "")
        local_path = str(sample.get("local_path") or "")
        if not sample_id or not local_path:
            continue
        image_path = Path(local_path)
        if not image_path.exists():
            continue
        if strategy_key == "aug_iou_disagreement":
            preds_by_aug = predict_with_aug(
                model=model,
                image_path=image_path,
                conf=conf,
                imgsz=imgsz,
                device=device,
                enabled_aug_names=aug_enabled_names,
            )
            score, reason = score_by_strategy(
                strategy_key,
                sample_id,
                random_seed=random_seed,
                round_index=round_index,
                predictions_by_aug=preds_by_aug,
                aug_iou_mode=aug_iou_mode,
                aug_iou_boundary_d=aug_iou_boundary_d,
            )
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                    "prediction_snapshot": {
                        "strategy": "aug_iou_disagreement",
                        "aug_count": len(preds_by_aug),
                        "pred_per_aug": [len(item) for item in preds_by_aug],
                        "base_predictions": [
                            export_prediction_entry(item)
                            for item in (preds_by_aug[0] if preds_by_aug else [])[:30]
                        ],
                    },
                }
            )
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, valid_total, sample_id)
            continue
        if strategy_key == "uncertainty_1_minus_max_conf":
            rows = predict_single_image(
                model=model,
                image_path=image_path,
                conf=conf,
                imgsz=imgsz,
                device=device,
            )
            score, reason = score_by_strategy(
                strategy_key,
                sample_id,
                random_seed=random_seed,
                round_index=round_index,
                predictions=rows,
            )
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                    "prediction_snapshot": {
                        "strategy": reason.get("strategy"),
                        "pred_count": len(rows),
                        "base_predictions": [export_prediction_entry(item) for item in rows[:30]],
                    },
                }
            )
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, valid_total, sample_id)
            continue

        if strategy_key == "random_baseline":
            score, reason = score_by_strategy(
                strategy_key,
                sample_id,
                random_seed=random_seed,
                round_index=round_index,
            )
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                }
            )
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, valid_total, sample_id)
            continue

        score, reason = score_by_strategy(
            strategy_key,
            sample_id,
            random_seed=random_seed,
            round_index=round_index,
        )
        candidates.append({"sample_id": sample_id, "score": score, "reason": reason})
        processed += 1
        if progress_callback is not None:
            progress_callback(processed, valid_total, sample_id)

    return candidates


def predict_with_augmentations(
    *,
    model: Any,
    image_path: Path,
    conf: float,
    imgsz: int,
    device: Any,
    ensure_image_deps: Callable[[], None],
    image_cls: Any,
    np_mod: Any,
    extract_predictions: Callable[[Any], list[dict[str, Any]]],
    extra_aug_specs: tuple[AugmentationSpec, ...] | list[AugmentationSpec] = (),
    enabled_aug_names: tuple[str, ...] | list[str] | None = None,
) -> list[list[dict[str, Any]]]:
    ensure_image_deps()
    with image_cls.open(image_path) as img:
        rgb = img.convert("RGB")
        image = np_mod.array(rgb)

    views = build_augmented_views(
        image,
        np_mod=np_mod,
        image_cls=image_cls,
        extra_specs=extra_aug_specs,
        enabled_names=enabled_aug_names,
    )
    if not views:
        return []

    sources = [view.image for view in views]
    predict_kwargs = {
        "source": sources,
        "conf": conf,
        "imgsz": imgsz,
        "device": device,
        "verbose": False,
        "batch": max(1, len(sources)),
    }
    try:
        predicts = model.predict(**predict_kwargs)
    except TypeError:
        predict_kwargs.pop("batch", None)
        predicts = model.predict(**predict_kwargs)
    predict_list = list(predicts or [])
    results_by_aug: list[list[dict[str, Any]]] = []
    for view, pred in zip_longest(views, predict_list):
        if view is None:
            break
        rows = extract_predictions(pred) if pred is not None else []
        rows = [inverse_augmented_prediction_row(item, view=view) for item in rows]
        results_by_aug.append(rows)
    return results_by_aug


def export_prediction_entry(item: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "class_index": int(item.get("class_index", 0)),
        "class_name": str(item.get("class_name") or ""),
        "confidence": float(item.get("confidence") or 0.0),
        "geometry": dict(item.get("geometry") or {}),
    }
    label_id = str(item.get("label_id") or "").strip()
    if label_id:
        out["label_id"] = label_id

    attrs_raw = item.get("attrs")
    attrs: dict[str, Any] = dict(attrs_raw) if isinstance(attrs_raw, Mapping) else {}
    qbox_raw = item.get("qbox")
    if qbox_raw is not None:
        qbox = tuple(float(v) for v in qbox_raw[:8]) if isinstance(qbox_raw, (list, tuple)) else None
        if qbox is not None and len(qbox) == 8:
            attrs.setdefault("qbox", list(qbox))
    if attrs:
        out["attrs"] = attrs
    return out
