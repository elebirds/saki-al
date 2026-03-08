from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Any, Callable


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
) -> list[dict[str, Any]]:
    strategy_key = normalize_strategy_name(strategy)
    need_model = strategy_key in {"aug_iou_disagreement", "uncertainty_1_minus_max_conf"}
    model = get_model() if need_model and callable(get_model) else None
    if need_model and model is None:
        raise RuntimeError(f"model is required for strategy={strategy_key}")
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
        if strategy_key == "aug_iou_disagreement":
            preds_by_aug = predict_with_aug(
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
                predictions_by_aug=preds_by_aug,
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
                        "base_predictions": preds_by_aug[0][:30] if preds_by_aug else [],
                    },
                }
            )
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
                        "base_predictions": rows[:30],
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
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                }
            )
            continue

        score, reason = score_by_strategy(
            strategy_key,
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
