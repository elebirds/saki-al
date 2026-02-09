from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Event
from typing import Any, Callable


def _stable_random_score(*, sample_id: str, random_seed: int, round_index: int) -> float:
    digest = hashlib.sha256(f"{random_seed}:{round_index}:{sample_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / float(0xFFFFFFFF)


def score_unlabeled_samples(
    *,
    model_path: str,
    unlabeled_samples: list[dict[str, Any]],
    strategy: str,
    conf: float,
    imgsz: int,
    device: Any,
    stop_flag: Event,
    load_yolo: Callable[[], Any],
    predict_with_aug: Callable[..., list[list[dict[str, Any]]]],
    extract_predictions: Callable[[Any], list[dict[str, Any]]],
    build_detection_boxes: Callable[[list[dict[str, Any]]], list[Any]],
    score_aug_iou_disagreement: Callable[[list[list[Any]]], tuple[float, dict[str, Any]]],
    score_by_strategy: Callable[..., tuple[float, dict[str, Any]]],
    random_seed: int,
    round_index: int,
) -> list[dict[str, Any]]:
    YOLO = load_yolo()
    model = YOLO(model_path)
    candidates: list[dict[str, Any]] = []

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
        if (strategy or "").lower() in {"aug_iou_disagreement_v1", "aug_iou_disagreement"}:
            preds_by_aug = predict_with_aug(
                model=model,
                image_path=image_path,
                conf=conf,
                imgsz=imgsz,
                device=device,
            )
            boxes_by_aug = [build_detection_boxes(item) for item in preds_by_aug]
            score, reason = score_aug_iou_disagreement(boxes_by_aug)
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                    "prediction_snapshot": {
                        "strategy": "aug_iou_disagreement_v1",
                        "aug_count": len(preds_by_aug),
                        "pred_per_aug": [len(item) for item in preds_by_aug],
                        "base_predictions": preds_by_aug[0][:30] if preds_by_aug else [],
                    },
                }
            )
            continue
        strategy_key = (strategy or "").lower()
        if strategy_key in {"uncertainty", "uncertainty_1_minus_max_conf", "plugin_native", "plugin_native_strategy"}:
            predicts = model.predict(
                source=str(image_path),
                conf=conf,
                imgsz=imgsz,
                device=device,
                verbose=False,
            )
            first = predicts[0] if predicts else None
            rows = extract_predictions(first)
            conf_values = [float(item.get("conf") or 0.0) for item in rows]
            max_conf = max(conf_values) if conf_values else 0.0
            uncertainty = 1.0 - max(0.0, min(1.0, max_conf))
            if strategy_key in {"plugin_native", "plugin_native_strategy"}:
                density = min(1.0, len(rows) / 20.0)
                score = max(0.0, min(1.0, 0.7 * uncertainty + 0.3 * density))
                reason = {
                    "strategy": "plugin_native_strategy",
                    "max_conf": max_conf,
                    "uncertainty": uncertainty,
                    "density": density,
                    "score": score,
                }
            else:
                score = uncertainty
                reason = {
                    "strategy": "uncertainty_1_minus_max_conf",
                    "max_conf": max_conf,
                    "pred_count": len(rows),
                }
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                    "prediction_snapshot": {
                        "strategy": reason.get("strategy"),
                        "pred_count": len(rows),
                        "base_predictions": rows[:30],
                    },
                }
            )
            continue

        if strategy_key in {"random", "random_baseline"}:
            score = _stable_random_score(sample_id=sample_id, random_seed=random_seed, round_index=round_index)
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": {
                        "strategy": "random_baseline",
                        "random_seed": int(random_seed),
                        "round_index": int(round_index),
                        "rand": score,
                    },
                }
            )
            continue

        score, reason = score_by_strategy(
            strategy,
            sample_id,
            random_seed=random_seed,
            round_index=round_index,
        )
        candidates.append({"sample_id": sample_id, "score": score, "reason": reason})

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
    inverse_aug_box: Callable[..., dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    ensure_image_deps()
    with image_cls.open(image_path) as img:
        rgb = img.convert("RGB")
        image = np_mod.array(rgb)

    h, w = image.shape[:2]
    transforms: list[tuple[str, Callable[[Any], Any]]] = [
        ("identity", lambda arr: arr),
        ("hflip", lambda arr: np_mod.ascontiguousarray(arr[:, ::-1, :])),
        ("vflip", lambda arr: np_mod.ascontiguousarray(arr[::-1, :, :])),
        ("bright", lambda arr: np_mod.clip(arr.astype(np_mod.float32) * 1.2, 0, 255).astype(np_mod.uint8)),
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
        rows = extract_predictions(first)
        rows = [inverse_aug_box(name=name, row=item, width=w, height=h) for item in rows]
        results_by_aug.append(rows)
    return results_by_aug
