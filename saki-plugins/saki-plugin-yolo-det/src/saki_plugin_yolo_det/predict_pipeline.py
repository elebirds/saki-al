from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from threading import Event
from typing import Any, Callable

from saki_plugin_sdk.augmentations import (
    AugmentationSpec,
    build_augmented_views,
    inverse_augmented_prediction_row,
)


@dataclass(frozen=True)
class PreparedAugmentedSample:
    sample_id: str
    image_path: Path
    sources: tuple[Any, ...]
    views: tuple[Any, ...]
    width: int
    height: int
    prepare_sec: float


def score_augmented_samples_with_pipeline(
    *,
    unlabeled_samples: list[dict[str, Any]],
    stop_flag: Event,
    model: Any,
    conf: float,
    imgsz: int,
    device: Any,
    random_seed: int,
    round_index: int,
    enabled_aug_names: tuple[str, ...] | list[str] | None,
    aug_iou_mode: str,
    aug_iou_boundary_d: int,
    predict_batch_size: int,
    sample_batch_size: int,
    pipeline_workers: int,
    prepare_sample: Callable[..., PreparedAugmentedSample],
    predict_batch: Callable[..., list[Any]],
    finalize_sample: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
    progress_callback: Callable[[int, int, str], None] | None = None,
    batch_callback: Callable[[dict[str, Any]], None] | None = None,
    sample_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    valid_samples = [
        (str(sample.get("id") or ""), Path(str(sample.get("local_path") or "")))
        for sample in unlabeled_samples
        if str(sample.get("id") or "").strip() and Path(str(sample.get("local_path") or "")).exists()
    ]
    if not valid_samples:
        return []

    normalized_sample_batch_size = max(1, int(sample_batch_size or 1))
    normalized_predict_batch_size = max(1, int(predict_batch_size or 1))
    normalized_pipeline_workers = max(1, int(pipeline_workers or 1))
    preprocess_inflight_limit = max(normalized_sample_batch_size, normalized_pipeline_workers * 2)
    postprocess_inflight_limit = max(normalized_sample_batch_size, normalized_pipeline_workers * 2)
    sample_iter = iter(valid_samples)
    prepared_buffer: list[PreparedAugmentedSample] = []
    pending_preprocess: dict[Future[PreparedAugmentedSample], tuple[str, Path]] = {}
    pending_postprocess: dict[Future[tuple[dict[str, Any], dict[str, Any]]], str] = {}
    candidates: list[dict[str, Any]] = []
    processed = 0
    batch_index = 0

    def _submit_preprocess_jobs(executor: ThreadPoolExecutor) -> None:
        while len(pending_preprocess) < preprocess_inflight_limit:
            try:
                sample_id, image_path = next(sample_iter)
            except StopIteration:
                return
            future = executor.submit(
                prepare_sample,
                sample_id=sample_id,
                image_path=image_path,
                enabled_aug_names=enabled_aug_names,
            )
            pending_preprocess[future] = (sample_id, image_path)

    def _drain_postprocess_results(*, wait_for_result: bool) -> bool:
        nonlocal processed
        if not pending_postprocess:
            return False
        timeout = None if wait_for_result else 0
        done, _ = wait(set(pending_postprocess), timeout=timeout, return_when=FIRST_COMPLETED)
        if not done:
            return False
        for future in done:
            pending_postprocess.pop(future, None)
            candidate, diag = future.result()
            candidates.append(candidate)
            processed += 1
            sample_id = str(candidate.get("sample_id") or diag.get("sample_id") or "")
            if progress_callback is not None:
                progress_callback(processed, len(valid_samples), sample_id)
            if sample_callback is not None:
                sample_callback(dict(diag))
        return True

    with (
        ThreadPoolExecutor(max_workers=normalized_pipeline_workers) as preprocess_executor,
        ThreadPoolExecutor(max_workers=normalized_pipeline_workers) as postprocess_executor,
    ):
        _submit_preprocess_jobs(preprocess_executor)
        while pending_preprocess or prepared_buffer or pending_postprocess:
            if stop_flag.is_set():
                raise RuntimeError("sampling stopped")

            if prepared_buffer and (
                len(prepared_buffer) >= normalized_sample_batch_size or not pending_preprocess
            ):
                batch_index += 1
                batch_samples = prepared_buffer[:normalized_sample_batch_size]
                del prepared_buffer[:normalized_sample_batch_size]
                sources: list[Any] = []
                sample_ranges: list[tuple[PreparedAugmentedSample, int, int]] = []
                for prepared in batch_samples:
                    start = len(sources)
                    sources.extend(prepared.sources)
                    sample_ranges.append((prepared, start, len(sources)))

                infer_started_at = time.perf_counter()
                predicts = list(
                    predict_batch(
                        model=model,
                        sources=sources,
                        conf=conf,
                        imgsz=imgsz,
                        device=device,
                        batch=normalized_predict_batch_size,
                    )
                    or []
                )
                infer_sec = time.perf_counter() - infer_started_at
                if batch_callback is not None:
                    batch_callback(
                        {
                            "batch_index": batch_index,
                            "sample_count": len(batch_samples),
                            "source_count": len(sources),
                            "predict_batch_size": normalized_predict_batch_size,
                            "sample_batch_size": normalized_sample_batch_size,
                            "pipeline_workers": normalized_pipeline_workers,
                            "infer_sec": infer_sec,
                        }
                    )
                for prepared, start, end in sample_ranges:
                    future = postprocess_executor.submit(
                        finalize_sample,
                        prepared_sample=prepared,
                        predictions=predicts[start:end],
                        random_seed=random_seed,
                        round_index=round_index,
                        aug_iou_mode=aug_iou_mode,
                        aug_iou_boundary_d=aug_iou_boundary_d,
                    )
                    pending_postprocess[future] = prepared.sample_id
                _submit_preprocess_jobs(preprocess_executor)
                if len(pending_postprocess) >= postprocess_inflight_limit:
                    _drain_postprocess_results(wait_for_result=True)
                else:
                    _drain_postprocess_results(wait_for_result=False)
                continue

            if pending_preprocess:
                wait_timeout = 0 if pending_postprocess else None
                done, _ = wait(
                    set(pending_preprocess),
                    timeout=wait_timeout,
                    return_when=FIRST_COMPLETED,
                )
                if not done and not prepared_buffer:
                    done, _ = wait(set(pending_preprocess), return_when=FIRST_COMPLETED)
                for future in done:
                    pending_preprocess.pop(future, None)
                    prepared_buffer.append(future.result())
                _submit_preprocess_jobs(preprocess_executor)
                if done:
                    _drain_postprocess_results(wait_for_result=False)
                    continue

            if _drain_postprocess_results(wait_for_result=not pending_preprocess and not prepared_buffer):
                continue

            if pending_preprocess:
                continue
            if not prepared_buffer and not pending_postprocess:
                break

    return candidates


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
