from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from threading import Event
from typing import Any

from saki_plugin_sdk import EventCallback, ExecutionBindingContext, TrainArtifact, TrainOutput, WorkspaceProtocol

from saki_plugin_oriented_rcnn.common import normalize_device
from saki_plugin_oriented_rcnn.config_builder import build_mmrotate_runtime_cfg, resolve_preset_checkpoint
from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.metrics_service import build_train_metrics
from saki_plugin_oriented_rcnn.mmrotate_adapter import evaluate_micro_pr, run_train_and_eval
from saki_plugin_oriented_rcnn.prepare_pipeline import load_class_schema, load_prepare_manifest


class OrientedRCNNTrainService:
    """训练服务。

    设计决策：
    1. `train` 完成后立即跑一轮标准评估，确保最终指标一次产出。
    2. 最终权重统一复制为 `artifacts/best.pth`，满足 executor 的主模型交接约定。
    """

    def __init__(
        self,
        *,
        stop_flag: Event,
        config_service: OrientedRCNNConfigService,
    ) -> None:
        self._stop_flag = stop_flag
        self._config_service = config_service

    async def train(
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

        # 根据执行器绑定结果选择真实 device。
        # 这里不直接使用用户配置 device，避免与 runtime binding 冲突。
        device = normalize_device(
            backend=str(context.device_binding.backend or ""),
            device_spec=str(context.device_binding.device_spec or ""),
        )

        model_ref = await self._config_service.resolve_model_ref(workspace=workspace, config=cfg)
        load_from = _resolve_model_checkpoint_ref(model_ref)

        runtime_cfg_path = workspace.cache_dir / "mmrotate_train_runtime.py"
        work_dir = workspace.root / "mmrotate_workdir" / "train"
        work_dir.mkdir(parents=True, exist_ok=True)

        build_mmrotate_runtime_cfg(
            output_path=runtime_cfg_path,
            data_root=workspace.data_dir,
            classes=classes,
            epochs=cfg.epochs,
            batch=cfg.batch,
            workers=cfg.workers,
            imgsz=cfg.imgsz,
            nms_iou_thr=cfg.nms_iou_thr,
            max_per_img=cfg.max_per_img,
            val_degraded=bool(manifest.get("val_degraded", False)),
            work_dir=work_dir,
            load_from=load_from,
            train_seed=int(cfg.train_seed or context.step_context.train_seed),
            deterministic=bool(cfg.deterministic),
            train_sample_count=int(manifest.get("train_sample_count") or 0),
        )

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "oriented_rcnn train start "
                    f"epochs={cfg.epochs} batch={cfg.batch} imgsz={cfg.imgsz} device={device} "
                    f"classes={len(classes)}"
                ),
            },
        )

        result = await asyncio.to_thread(
            run_train_and_eval,
            config_path=runtime_cfg_path,
        )

        checkpoint = Path(str(result.get("checkpoint") or ""))
        if not checkpoint.exists():
            raise RuntimeError(f"train checkpoint not found: {checkpoint}")

        # 单独执行 IoU=0.5 细粒度 PR 评估，用于精确计算 precision/recall。
        eval_details = await asyncio.to_thread(
            evaluate_micro_pr,
            config_path=runtime_cfg_path,
            checkpoint=str(checkpoint),
            device=device,
        )

        canonical = build_train_metrics(
            raw_eval_metrics=dict(result.get("eval_metrics") or {}),
            eval_details=eval_details,
            loss_value=float(result.get("loss") or 0.0),
        )

        best_artifact = workspace.artifacts_dir / "best.pth"
        shutil.copy2(checkpoint, best_artifact)

        report_path = workspace.artifacts_dir / "train_report.json"
        report_payload = {
            "metrics": canonical.to_train_metrics(),
            "raw_eval_metrics": dict(result.get("eval_metrics") or {}),
            "eval_details_summary": {
                "class_count": len(eval_details),
            },
            "prepare_manifest": manifest,
            "runtime": {
                "device": device,
                "profile_id": context.profile_id,
                "task_id": context.step_context.task_id,
                "round_index": context.step_context.round_index,
                "train_seed": context.step_context.train_seed,
                "split_seed": context.step_context.split_seed,
                "sampling_seed": context.step_context.sampling_seed,
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
                kind="weights",
                name="best.pth",
                path=best_artifact,
                content_type="application/octet-stream",
                required=True,
            ),
            TrainArtifact(
                kind="report",
                name="train_report.json",
                path=report_path,
                content_type="application/json",
                required=True,
            ),
        ]

        return TrainOutput(
            metrics=canonical.to_train_metrics(),
            artifacts=artifacts,
        )


def _resolve_model_checkpoint_ref(model_ref: str) -> str:
    text = str(model_ref or "").strip()
    if not text:
        raise RuntimeError("model_ref is empty")

    # 预设模型 ID 需要映射到官方 checkpoint URL。
    if text in {"oriented-rcnn-le90_r50_fpn_1x_dota"}:
        return resolve_preset_checkpoint(text)

    return text
