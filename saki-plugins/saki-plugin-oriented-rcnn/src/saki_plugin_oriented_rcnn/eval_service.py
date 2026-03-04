from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Event
from typing import Any

from saki_plugin_sdk import EventCallback, ExecutionBindingContext, TrainArtifact, TrainOutput, WorkspaceProtocol

from saki_plugin_oriented_rcnn.common import normalize_device
from saki_plugin_oriented_rcnn.config_builder import build_mmrotate_runtime_cfg, resolve_preset_checkpoint
from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.metrics_service import build_eval_metrics
from saki_plugin_oriented_rcnn.mmrotate_adapter import evaluate_micro_pr, run_eval_only
from saki_plugin_oriented_rcnn.prepare_pipeline import load_class_schema, load_prepare_manifest


class OrientedRCNNEvalService:
    def __init__(
        self,
        *,
        stop_flag: Event,
        config_service: OrientedRCNNConfigService,
    ) -> None:
        self._stop_flag = stop_flag
        self._config_service = config_service

    async def eval(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._stop_flag.clear()
        cfg = self._config_service.resolve_config(params)

        manifest = load_prepare_manifest(workspace)
        schema = load_class_schema(workspace)
        classes = tuple(str(v) for v in (schema.get("classes") or []) if str(v).strip())
        if not classes:
            raise RuntimeError("prepare_data output missing classes; class_schema.json not found or empty")

        device = normalize_device(
            backend=str(context.device_binding.backend or ""),
            device_spec=str(context.device_binding.device_spec or ""),
        )

        model_ref = await self._config_service.resolve_best_or_fallback_model(workspace=workspace, config=cfg)
        checkpoint_ref = _resolve_model_checkpoint_ref(model_ref)

        runtime_cfg_path = workspace.cache_dir / "mmrotate_eval_runtime.py"
        work_dir = workspace.root / "mmrotate_workdir" / "eval"
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
            val_degraded=bool(manifest.get("val_degraded", False)),
            work_dir=work_dir,
            load_from=checkpoint_ref,
            train_seed=int(cfg.train_seed or context.step_context.train_seed),
        )

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "oriented_rcnn eval start "
                    f"device={device} checkpoint={checkpoint_ref} classes={len(classes)}"
                ),
            },
        )

        result = await asyncio.to_thread(
            run_eval_only,
            config_path=runtime_cfg_path,
            checkpoint=checkpoint_ref,
        )

        eval_details = await asyncio.to_thread(
            evaluate_micro_pr,
            config_path=runtime_cfg_path,
            checkpoint=checkpoint_ref,
            device=device,
        )

        canonical = build_eval_metrics(
            raw_eval_metrics=dict(result.get("eval_metrics") or {}),
            eval_details=eval_details,
        )

        report_path = workspace.artifacts_dir / "eval_report.json"
        report_payload = {
            "metrics": canonical.to_eval_metrics(),
            "raw_eval_metrics": dict(result.get("eval_metrics") or {}),
            "eval_details_summary": {
                "class_count": len(eval_details),
            },
            "runtime": {
                "device": device,
                "profile_id": context.profile_id,
                "runtime_cfg_path": str(runtime_cfg_path),
                "work_dir": str(result.get("work_dir") or work_dir),
            },
        }
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        artifacts = [
            TrainArtifact(
                kind="report",
                name="eval_report.json",
                path=report_path,
                content_type="application/json",
                required=True,
            )
        ]

        return TrainOutput(
            metrics=canonical.to_eval_metrics(),
            artifacts=artifacts,
        )


def _resolve_model_checkpoint_ref(model_ref: str) -> str:
    text = str(model_ref or "").strip()
    if not text:
        raise RuntimeError("model_ref is empty")
    if text in {"oriented-rcnn-le90_r50_fpn_1x_dota"}:
        return resolve_preset_checkpoint(text)
    return text
