from __future__ import annotations

import asyncio
import hashlib
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
        class_rows: list[dict[str, Any]] = []
        for idx, item in enumerate(labels):
            label_id = str(item.get("id") or "").strip()
            if not label_id:
                continue
            class_name = str(item.get("name") or f"class_{idx}")
            class_rows.append(
                {
                    "class_index": idx,
                    "label_id": label_id,
                    "class_name": class_name,
                    "class_name_norm": " ".join(class_name.strip().lower().split()),
                }
            )
        (workspace.data_dir / "class_schema.json").write_text(
            json.dumps({"version": 1, "classes": class_rows}, ensure_ascii=False, indent=2),
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
        task_context = context.task_context
        epochs = int(params.get("epochs", 5))
        steps_per_epoch = int(params.get("steps_per_epoch", 20))

        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "training started "
                    f"task_type={task_context.task_type} mode={task_context.mode} "
                    f"split_seed={task_context.split_seed} train_seed={task_context.train_seed} "
                    f"sampling_seed={task_context.sampling_seed}"
                ),
            },
        )
        metrics: dict[str, Any] = {}
        for epoch in range(1, epochs + 1):
            await asyncio.sleep(0.1)
            loss = max(0.01, 1.0 / epoch)
            map50 = min(0.99, 0.3 + epoch * 0.08)
            map50_95 = min(0.99, 0.18 + epoch * 0.07)
            precision = min(0.99, 0.35 + epoch * 0.06)
            recall = min(0.99, 0.4 + epoch * 0.05)
            metrics = {
                "map50": map50,
                "map50_95": map50_95,
                "precision": precision,
                "recall": recall,
                "loss": loss,
            }
            await emit("progress", {"epoch": epoch, "step": steps_per_epoch, "total_steps": steps_per_epoch, "eta_sec": 0})
            await emit("metric", {"step": epoch, "epoch": epoch, "metrics": metrics})

        report_meta = {
            "context_task_type": task_context.task_type,
            "context_mode": task_context.mode,
            "context_split_seed": float(task_context.split_seed),
            "context_train_seed": float(task_context.train_seed),
            "context_sampling_seed": float(task_context.sampling_seed),
        }

        model_path = workspace.artifacts_dir / "best.pt"
        report_path = workspace.artifacts_dir / "report.json"
        class_schema_path = workspace.data_dir / "class_schema.json"
        model_path.write_text("demo-model-weights", encoding="utf-8")
        report_path.write_text(
            json.dumps({"metrics": metrics, "meta": report_meta}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not class_schema_path.is_file():
            class_schema_path.write_text(json.dumps({"version": 1, "classes": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        class_rows: list[dict[str, Any]] = []
        if class_schema_path.is_file():
            try:
                schema_payload = json.loads(class_schema_path.read_text(encoding="utf-8"))
            except Exception:
                schema_payload = {}
            classes_raw = schema_payload.get("classes") if isinstance(schema_payload, dict) else []
            if isinstance(classes_raw, list):
                class_rows = [dict(item) for item in classes_raw if isinstance(item, dict)]
        schema_hash = hashlib.sha256(
            json.dumps(class_rows, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

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
                TrainArtifact(
                    kind="class_schema",
                    name="class_schema.json",
                    path=class_schema_path,
                    content_type="application/json",
                    meta={"class_schema_rows": class_rows, "schema_hash": schema_hash},
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
            "map50": 0.55,
            "map50_95": 0.42,
            "precision": 0.63,
            "recall": 0.61,
        }
        await emit("metric", {"step": 1, "epoch": 0, "metrics": metrics})
        report_path = workspace.artifacts_dir / "eval_report.json"
        report_path.write_text(
            json.dumps({"metrics": metrics, "meta": {"sample_count": sample_count}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
            candidates.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason,
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "class_name": "demo",
                                "confidence": float(score),
                                "geometry": {
                                    "rect": {
                                        "x": 10.0,
                                        "y": 10.0,
                                        "width": 90.0,
                                        "height": 90.0,
                                    }
                                },
                            }
                        ]
                    },
                }
            )
        candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        topk = int(params.get("topk", 200))
        return candidates[:topk]

    async def predict_samples_batch(
            self,
            workspace: WorkspaceProtocol,
            samples: list[dict[str, Any]],
            params: dict[str, Any],
            *,
            context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        del workspace, params, context
        rows: list[dict[str, Any]] = []
        for sample in samples:
            sample_id = str(sample.get("id") or "")
            if not sample_id:
                continue
            score = 0.9
            rows.append(
                {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": {
                        "mode": "predict",
                        "pred_count": 1,
                    },
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "class_name": "demo",
                                "confidence": score,
                                "geometry": {
                                    "rect": {
                                        "x": 10.0,
                                        "y": 10.0,
                                        "width": 90.0,
                                        "height": 90.0,
                                    }
                                },
                            }
                        ]
                    },
                }
            )
        return rows

    async def stop(self, task_id: str) -> None:
        return
