from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from saki_plugin_sdk import EventCallback, ExecutionBindingContext, TrainArtifact, TrainOutput, WorkspaceProtocol
from saki_plugin_yolo_det.common import to_int, to_yolo_device
from saki_plugin_yolo_det.config_service import YoloConfigService

_EVAL_CANONICAL_KEYS: tuple[str, ...] = ("map50", "map50_95", "precision", "recall")
_EVAL_ARTIFACT_PATTERNS: tuple[str, ...] = (
    "confusion_matrix*.png",
    "*F1_curve.png",
    "*PR_curve.png",
    "*P_curve.png",
    "*R_curve.png",
    "val_batch*_labels.jpg",
    "val_batch*_labels.png",
    "val_batch*_pred.jpg",
    "val_batch*_pred.png",
)
_SCOPE_TEST_ANCHOR = "test_anchor"
_SCOPE_TEST_BATCH = "test_batch"
_SCOPE_TEST_COMPOSITE = "test_composite"


class YoloEvalService:
    def __init__(
        self,
        *,
        config_service: YoloConfigService,
        load_yolo: Callable[[], Any],
        normalize_metrics: Callable[[dict[str, Any] | Any], dict[str, float]],
    ) -> None:
        self._config_service = config_service
        self._load_yolo = load_yolo
        self._normalize_metrics = normalize_metrics

    async def eval(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        cfg = self._config_service.resolve_config(params)
        dataset_yaml = workspace.data_dir / "dataset.yaml"
        if not dataset_yaml.exists():
            raise RuntimeError(f"dataset file not found: {dataset_yaml}")

        requested_device = str(getattr(cfg, "device", "auto") or "auto").strip().lower()
        resolved_backend = str(context.device_binding.backend or "").strip().lower()
        device = to_yolo_device(resolved_backend, str(context.device_binding.device_spec or ""))
        model_path = await self._config_service.resolve_best_or_fallback_model(workspace=workspace, params=cfg)
        imgsz = to_int(cfg.imgsz, 640)
        batch = to_int(cfg.batch, 16)
        mode = str(getattr(context.task_context, "mode", "") or "").strip().lower()

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"YOLO 评估开始 model={model_path} imgsz={imgsz} batch={batch} "
                    f"requested_device={requested_device} resolved_backend={resolved_backend} "
                    f"device={device} profile={context.profile_id} mode={mode}"
                ),
            },
        )

        manifest = self._load_dataset_manifest(workspace)
        scope_sample_ids = self._resolve_scope_sample_ids(manifest=manifest)
        anchor_ids = scope_sample_ids.get(_SCOPE_TEST_ANCHOR, [])
        batch_ids = scope_sample_ids.get(_SCOPE_TEST_BATCH, [])
        composite_ids = sorted(set(anchor_ids).union(batch_ids))

        has_partition_scope = bool(anchor_ids or batch_ids)
        scope_plan: list[tuple[str, int, list[str]]] = []
        if has_partition_scope:
            scope_plan = [
                (_SCOPE_TEST_ANCHOR, 1, anchor_ids),
                (_SCOPE_TEST_BATCH, 2, batch_ids),
                (_SCOPE_TEST_COMPOSITE, 3, composite_ids),
            ]
        else:
            scope_plan = [(_SCOPE_TEST_ANCHOR, 1, [])]

        metrics_by_scope: dict[str, dict[str, float]] = {}
        sample_count_by_scope: dict[str, int] = {}
        raw_metrics_by_scope: dict[str, dict[str, Any]] = {}
        all_extra_artifacts: list[tuple[str, str]] = []

        for scope_key, step_index, sample_ids in scope_plan:
            scoped_dataset = (
                self._build_scoped_dataset_file(
                    workspace=workspace,
                    base_dataset_yaml=dataset_yaml,
                    scope_key=scope_key,
                    sample_ids=sample_ids,
                )
                if has_partition_scope
                else dataset_yaml
            )
            if has_partition_scope and scoped_dataset is None:
                metrics_by_scope[scope_key] = {}
                sample_count_by_scope[scope_key] = 0
                raw_metrics_by_scope[scope_key] = {}
                continue

            eval_result = await asyncio.to_thread(
                self._run_eval_sync,
                workspace=workspace,
                model_path=model_path,
                dataset_yaml=scoped_dataset or dataset_yaml,
                imgsz=imgsz,
                batch=batch,
                device=device,
                run_name=f"eval_{scope_key}",
            )
            normalized_metrics = self._normalize_metrics(eval_result.get("metrics", {}))
            metrics_by_scope[scope_key] = dict(normalized_metrics)
            raw_metrics_by_scope[scope_key] = dict(eval_result.get("metrics", {}))
            sample_count_by_scope[scope_key] = int(eval_result.get("sample_count") or 0)
            all_extra_artifacts.extend((scope_key, item) for item in eval_result.get("extra_artifacts", []))
            if normalized_metrics:
                await emit("metric", {"step": step_index, "epoch": 0, "metrics": dict(normalized_metrics)})
            await emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "评估分口径完成 "
                        f"scope={scope_key} step={step_index} samples={sample_count_by_scope[scope_key]} "
                        f"metric_keys={sorted(normalized_metrics.keys())}"
                    ),
                },
            )

        if has_partition_scope and _SCOPE_TEST_COMPOSITE not in metrics_by_scope:
            metrics_by_scope[_SCOPE_TEST_COMPOSITE] = {}
            raw_metrics_by_scope[_SCOPE_TEST_COMPOSITE] = {}
            sample_count_by_scope[_SCOPE_TEST_COMPOSITE] = 0

        primary_scope = _SCOPE_TEST_ANCHOR
        primary_metrics = dict(metrics_by_scope.get(_SCOPE_TEST_ANCHOR) or {})
        if not primary_metrics:
            fallback_scope = (
                _SCOPE_TEST_COMPOSITE
                if metrics_by_scope.get(_SCOPE_TEST_COMPOSITE)
                else _SCOPE_TEST_BATCH
            )
            fallback_metrics = dict(metrics_by_scope.get(fallback_scope) or {})
            if fallback_metrics:
                primary_scope = fallback_scope
                primary_metrics = fallback_metrics
                await emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": (
                            "评估 anchor 口径指标为空，已回退 "
                            f"fallback_scope={fallback_scope}"
                        ),
                    },
                )

        metrics_source = f"scope:{primary_scope}" if primary_metrics else "none"
        missing_canonical = [key for key in _EVAL_CANONICAL_KEYS if key not in primary_metrics]
        if (not primary_metrics) or missing_canonical:
            await emit(
                "log",
                {
                    "level": "WARN",
                    "message": (
                        "评估最终指标不完整 "
                        f"source={metrics_source} available={sorted(primary_metrics.keys())} "
                        f"missing={missing_canonical}"
                    ),
                },
            )

        report_path = workspace.artifacts_dir / "eval_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "metrics": primary_metrics,
                    "primary_scope": primary_scope,
                    "metrics_by_scope": {
                        _SCOPE_TEST_ANCHOR: metrics_by_scope.get(_SCOPE_TEST_ANCHOR, {}),
                        _SCOPE_TEST_BATCH: metrics_by_scope.get(_SCOPE_TEST_BATCH, {}),
                        _SCOPE_TEST_COMPOSITE: metrics_by_scope.get(_SCOPE_TEST_COMPOSITE, {}),
                    },
                    "raw_metrics_by_scope": {
                        _SCOPE_TEST_ANCHOR: raw_metrics_by_scope.get(_SCOPE_TEST_ANCHOR, {}),
                        _SCOPE_TEST_BATCH: raw_metrics_by_scope.get(_SCOPE_TEST_BATCH, {}),
                        _SCOPE_TEST_COMPOSITE: raw_metrics_by_scope.get(_SCOPE_TEST_COMPOSITE, {}),
                    },
                    "sample_count_by_scope": {
                        _SCOPE_TEST_ANCHOR: int(sample_count_by_scope.get(_SCOPE_TEST_ANCHOR, 0)),
                        _SCOPE_TEST_BATCH: int(sample_count_by_scope.get(_SCOPE_TEST_BATCH, 0)),
                        _SCOPE_TEST_COMPOSITE: int(sample_count_by_scope.get(_SCOPE_TEST_COMPOSITE, 0)),
                    },
                    "model_path": model_path,
                    "metric_validation": {
                        "source": metrics_source,
                        "missing_canonical_keys": missing_canonical,
                        "available_keys": sorted(primary_metrics.keys()),
                        "is_empty": not bool(primary_metrics),
                        "fallback_applied": primary_scope != _SCOPE_TEST_ANCHOR,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        artifacts: list[TrainArtifact] = [
            TrainArtifact(
                kind="report",
                name="eval_report.json",
                path=report_path,
                content_type="application/json",
                required=True,
            )
        ]
        for scope_key, item in all_extra_artifacts:
            path = Path(str(item))
            if not path.exists():
                continue
            artifacts.append(
                TrainArtifact(
                    kind="eval_artifact",
                    name=f"{scope_key}_{path.name}",
                    path=path,
                    content_type="application/octet-stream",
                    required=False,
                )
            )
        return TrainOutput(metrics=primary_metrics, artifacts=artifacts)

    def _run_eval_sync(
        self,
        *,
        workspace: WorkspaceProtocol,
        model_path: str,
        dataset_yaml: Path,
        imgsz: int,
        batch: int,
        device: Any,
        run_name: str,
    ) -> dict[str, Any]:
        yolo_cls = self._load_yolo()
        model = yolo_cls(model_path)
        try:
            project_dir = workspace.artifacts_dir.resolve()
        except Exception:
            project_dir = workspace.artifacts_dir.absolute()
        result = model.val(
            data=str(dataset_yaml),
            imgsz=imgsz,
            batch=batch,
            device=device,
            plots=True,
            verbose=False,
            project=str(project_dir),
            name=run_name,
            exist_ok=True,
        )
        metrics_raw = getattr(result, "results_dict", {}) or {}
        save_dir_raw = getattr(result, "save_dir", "")
        save_dir = Path(str(save_dir_raw)) if save_dir_raw else None
        extra_artifacts: list[str] = []
        if save_dir and save_dir.exists():
            discovered: dict[str, str] = {}
            for pattern in _EVAL_ARTIFACT_PATTERNS:
                for path in sorted(save_dir.glob(pattern)):
                    if not path.is_file():
                        continue
                    discovered.setdefault(path.name, str(path))
            extra_artifacts = [discovered[name] for name in sorted(discovered.keys())]
        sample_count = self._count_eval_samples_from_dataset_yaml(dataset_yaml)
        return {
            "metrics": dict(metrics_raw) if isinstance(metrics_raw, dict) else {},
            "save_dir": str(save_dir) if save_dir else "",
            "extra_artifacts": extra_artifacts,
            "sample_count": sample_count,
        }

    def _count_eval_samples_from_dataset_yaml(self, dataset_yaml: Path) -> int:
        try:
            payload = json.loads(dataset_yaml.read_text(encoding="utf-8"))
        except Exception:
            return 0
        val_ref = str((payload if isinstance(payload, dict) else {}).get("val") or "").strip()
        if not val_ref:
            return 0
        val_path = Path(val_ref)
        if not val_path.is_absolute():
            val_path = dataset_yaml.parent / val_ref
        if val_path.is_file():
            try:
                return len([line for line in val_path.read_text(encoding="utf-8").splitlines() if line.strip()])
            except Exception:
                return 0
        if val_path.is_dir():
            return len([item for item in val_path.glob("*.jpg") if item.is_file()])
        return 0

    def _load_dataset_manifest(self, workspace: WorkspaceProtocol) -> dict[str, Any]:
        manifest_path = workspace.data_dir / "dataset_manifest.json"
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _resolve_scope_sample_ids(self, *, manifest: dict[str, Any]) -> dict[str, list[str]]:
        raw = manifest.get("snapshot_partition_sample_ids")
        scope_ids: dict[str, list[str]] = {}
        if not isinstance(raw, dict):
            return scope_ids
        for key in (_SCOPE_TEST_ANCHOR, _SCOPE_TEST_BATCH):
            rows = raw.get(key)
            if not isinstance(rows, list):
                scope_ids[key] = []
                continue
            normalized = sorted({str(item).strip() for item in rows if str(item).strip()})
            scope_ids[key] = normalized
        return scope_ids

    def _build_scoped_dataset_file(
        self,
        *,
        workspace: WorkspaceProtocol,
        base_dataset_yaml: Path,
        scope_key: str,
        sample_ids: list[str],
    ) -> Path | None:
        if not sample_ids:
            return None
        try:
            base_payload = json.loads(base_dataset_yaml.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(base_payload, dict):
            return None

        data_root = workspace.data_dir
        image_paths: list[str] = []
        for sample_id in sample_ids:
            normalized = str(sample_id or "").strip()
            if not normalized:
                continue
            candidates = (
                data_root / "images" / "train" / f"{normalized}.jpg",
                data_root / "images" / "val" / f"{normalized}.jpg",
            )
            resolved = next((str(path.resolve()) for path in candidates if path.exists()), "")
            if resolved:
                image_paths.append(resolved)
        if not image_paths:
            return None

        list_path = workspace.artifacts_dir / f"eval_scope_{scope_key}.txt"
        list_path.write_text("\n".join(image_paths) + "\n", encoding="utf-8")

        scoped_payload = dict(base_payload)
        scoped_payload["val"] = str(list_path.resolve())
        scoped_payload["test"] = str(list_path.resolve())
        scoped_yaml = workspace.artifacts_dir / f"eval_scope_{scope_key}.json"
        scoped_yaml.write_text(json.dumps(scoped_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return scoped_yaml
