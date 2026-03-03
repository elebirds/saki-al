from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from saki_plugin_sdk import EventCallback, ExecutionBindingContext, TrainArtifact, TrainOutput, WorkspaceProtocol
from saki_plugin_yolo_det.common import to_int, to_yolo_device
from saki_plugin_yolo_det.config_service import YoloConfigService


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

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"YOLO eval started model={model_path} imgsz={imgsz} batch={batch} "
                    f"requested_device={requested_device} resolved_backend={resolved_backend} "
                    f"device={device} profile={context.profile_id}"
                ),
            },
        )

        eval_result = await asyncio.to_thread(
            self._run_eval_sync,
            workspace=workspace,
            model_path=model_path,
            dataset_yaml=dataset_yaml,
            imgsz=imgsz,
            batch=batch,
            device=device,
        )
        metrics = self._normalize_metrics(eval_result.get("metrics", {}))
        await emit("metric", {"step": 1, "epoch": 0, "metrics": metrics})

        report_path = workspace.artifacts_dir / "eval_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "metrics": metrics,
                    "raw_metrics": eval_result.get("metrics", {}),
                    "save_dir": eval_result.get("save_dir", ""),
                    "model_path": model_path,
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
        for item in eval_result.get("extra_artifacts", []):
            path = Path(str(item))
            if not path.exists():
                continue
            artifacts.append(
                TrainArtifact(
                    kind="eval_artifact",
                    name=path.name,
                    path=path,
                    content_type="application/octet-stream",
                    required=False,
                )
            )
        return TrainOutput(metrics=metrics, artifacts=artifacts)

    def _run_eval_sync(
        self,
        *,
        workspace: WorkspaceProtocol,
        model_path: str,
        dataset_yaml: Path,
        imgsz: int,
        batch: int,
        device: Any,
    ) -> dict[str, Any]:
        yolo_cls = self._load_yolo()
        model = yolo_cls(model_path)
        result = model.val(
            data=str(dataset_yaml),
            imgsz=imgsz,
            batch=batch,
            device=device,
            plots=True,
            verbose=False,
            project=str(workspace.artifacts_dir),
            name="eval",
            exist_ok=True,
        )
        metrics_raw = getattr(result, "results_dict", {}) or {}
        save_dir_raw = getattr(result, "save_dir", "")
        save_dir = Path(str(save_dir_raw)) if save_dir_raw else None
        extra_artifacts: list[str] = []
        if save_dir and save_dir.exists():
            for filename in (
                "confusion_matrix.png",
                "confusion_matrix_normalized.png",
                "F1_curve.png",
                "P_curve.png",
                "R_curve.png",
                "PR_curve.png",
            ):
                path = save_dir / filename
                if path.exists():
                    extra_artifacts.append(str(path))
        return {
            "metrics": dict(metrics_raw) if isinstance(metrics_raw, dict) else {},
            "save_dir": str(save_dir) if save_dir else "",
            "extra_artifacts": extra_artifacts,
        }
