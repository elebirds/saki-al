from __future__ import annotations

import asyncio
import json
from typing import Any

from saki_plugin_sdk import ExecutionBindingContext, EventCallback, TrainArtifact, TrainOutput, WorkspaceProtocol
from saki_plugin_sdk.strategies.builtin import score_by_strategy


class DemoDetectionInternal:
    async def prepare_data(
            self,
            workspace: WorkspaceProtocol,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: ExecutionBindingContext,
    ) -> None:
        del splits, context
        payload = {
            "labels": labels,
            "sample_count": len(samples),
            "annotation_count": len(annotations),
            "ir_item_count": len(dataset_ir.items) if dataset_ir is not None else 0,
        }
        (workspace.data_dir / "dataset_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def train(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: ExecutionBindingContext,
    ) -> TrainOutput:
        step_context = context.step_context
        epochs = int(params.get("epochs", 5))
        steps_per_epoch = int(params.get("steps_per_epoch", 20))

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "training started "
                    f"step_type={step_context.step_type} mode={step_context.mode} "
                    f"split_seed={step_context.split_seed} train_seed={step_context.train_seed} "
                    f"sampling_seed={step_context.sampling_seed}"
                ),
            },
        )
        metrics: dict[str, Any] = {}
        for epoch in range(1, epochs + 1):
            await asyncio.sleep(0.1)
            loss = max(0.01, 1.0 / epoch)
            map50 = min(0.99, 0.3 + epoch * 0.08)
            recall = min(0.99, 0.4 + epoch * 0.05)
            metrics = {"loss": loss, "map50": map50, "recall": recall}
            await emit("progress", {"epoch": epoch, "step": steps_per_epoch, "total_steps": steps_per_epoch, "eta_sec": 0})
            await emit("metric", {"step": epoch, "epoch": epoch, "metrics": metrics})

        metrics["context_step_type"] = step_context.step_type
        metrics["context_mode"] = step_context.mode
        metrics["context_split_seed"] = float(step_context.split_seed)
        metrics["context_train_seed"] = float(step_context.train_seed)
        metrics["context_sampling_seed"] = float(step_context.sampling_seed)

        model_path = workspace.artifacts_dir / "best.pt"
        report_path = workspace.artifacts_dir / "report.json"
        model_path.write_text("demo-model-weights", encoding="utf-8")
        report_path.write_text(json.dumps({"metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")

        return TrainOutput(
            metrics=metrics,
            artifacts=[
                TrainArtifact(
                    kind="weights",
                    name="best.pt",
                    path=model_path,
                    content_type="application/octet-stream",
                    required=True,
                ),
                TrainArtifact(
                    kind="report",
                    name="report.json",
                    path=report_path,
                    content_type="application/json",
                    required=True,
                ),
            ],
        )

    async def eval(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: ExecutionBindingContext,
    ) -> TrainOutput:
        del params, context
        await emit("log", {"level": "INFO", "message": "eval step started"})
        manifest_path = workspace.data_dir / "dataset_manifest.json"
        sample_count = 0
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                sample_count = int(payload.get("sample_count") or 0)
            except Exception:
                sample_count = 0
        metrics = {
            "eval_map50": 0.55,
            "eval_recall": 0.61,
            "eval_sample_count": float(sample_count),
        }
        await emit("metric", {"step": 1, "epoch": 0, "metrics": metrics})
        report_path = workspace.artifacts_dir / "eval_report.json"
        report_path.write_text(json.dumps({"metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")
        return TrainOutput(
            metrics=metrics,
            artifacts=[
                TrainArtifact(
                    kind="report",
                    name="eval_report.json",
                    path=report_path,
                    content_type="application/json",
                    required=True,
                )
            ],
        )

    async def predict_unlabeled(
            self,
            workspace: WorkspaceProtocol,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        del workspace, context
        candidates: list[dict[str, Any]] = []
        for sample in unlabeled_samples:
            sample_id = str(sample.get("id") or "")
            if not sample_id:
                continue
            score, reason = score_by_strategy(strategy, sample_id)
            candidates.append({"sample_id": sample_id, "score": score, "reason": reason})
        candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        topk = int(params.get("topk", 200))
        return candidates[:topk]

    async def stop(self, step_id: str) -> None:
        return
