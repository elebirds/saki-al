from __future__ import annotations

import asyncio
import json
from typing import Any

from saki_plugin_sdk import TrainArtifact, TrainOutput, EventCallback, Workspace
from saki_plugin_sdk.strategies.builtin import score_by_strategy


class DemoDetectionInternal:
    @property
    def plugin_id(self) -> str:
        return "demo_det_v1"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def display_name(self) -> str:
        return "Demo Detection (Mock)"

    @property
    def supported_step_types(self) -> list[str]:
        return [
            "train",
            "score",
            "eval",
            "export",
            "upload_artifact",
            "custom",
        ]

    @property
    def supported_strategies(self) -> list[str]:
        return [
            "uncertainty_1_minus_max_conf",
            "aug_iou_disagreement",
            "random_baseline",
        ]

    def config_schema(self, mode: str | None = None) -> dict[str, Any]:
        del mode
        return {
            "title": "Demo Detection Request Config",
            "fields": [
                {"key": "epochs", "label": "Epochs", "type": "integer", "required": True, "min": 1, "max": 500},
                {"key": "batch_size", "label": "Batch Size", "type": "integer", "required": True, "min": 1, "max": 2048},
                {"key": "steps_per_epoch", "label": "Steps / Epoch", "type": "integer", "required": False, "min": 1, "max": 5000},
            ],
        }

    def default_config(self, mode: str | None = None) -> dict[str, Any]:
        del mode
        return {
            "epochs": 5,
            "batch_size": 8,
            "steps_per_epoch": 20,
        }

    def validate_params(self, params: dict[str, Any]) -> None:
        epochs = int(params.get("epochs", 5))
        if epochs <= 0:
            raise ValueError("epochs must be > 0")
        batch_size = int(params.get("batch_size", 8))
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")

    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        del splits
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
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        epochs = int(params.get("epochs", 5))
        steps_per_epoch = int(params.get("steps_per_epoch", 20))

        await emit("log", {"level": "INFO", "message": "training started"})
        metrics: dict[str, Any] = {}
        for epoch in range(1, epochs + 1):
            await asyncio.sleep(0.1)
            loss = max(0.01, 1.0 / epoch)
            map50 = min(0.99, 0.3 + epoch * 0.08)
            recall = min(0.99, 0.4 + epoch * 0.05)
            metrics = {"loss": loss, "map50": map50, "recall": recall}
            await emit("progress", {"epoch": epoch, "step": steps_per_epoch, "total_steps": steps_per_epoch, "eta_sec": 0})
            await emit("metric", {"step": epoch, "epoch": epoch, "metrics": metrics})

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
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        del params
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

    async def export(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        del params
        await emit("log", {"level": "INFO", "message": "export step started"})
        export_path = workspace.artifacts_dir / "model.onnx"
        export_path.write_text("demo-exported-onnx", encoding="utf-8")
        return TrainOutput(
            metrics={"exported": 1.0},
            artifacts=[
                TrainArtifact(
                    kind="model_export",
                    name="model.onnx",
                    path=export_path,
                    content_type="application/octet-stream",
                    required=True,
                )
            ],
        )

    async def upload_artifact(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        del params
        await emit("log", {"level": "INFO", "message": "upload_artifact step started"})
        manifest_path = workspace.artifacts_dir / "upload_manifest.json"
        manifest_path.write_text(json.dumps({"status": "ready"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return TrainOutput(
            metrics={"upload_manifest_ready": 1.0},
            artifacts=[
                TrainArtifact(
                    kind="report",
                    name="upload_manifest.json",
                    path=manifest_path,
                    content_type="application/json",
                    required=True,
                )
            ],
        )

    async def predict_unlabeled(
            self,
            workspace: Workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
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
