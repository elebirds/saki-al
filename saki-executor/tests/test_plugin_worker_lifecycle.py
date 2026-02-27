import asyncio
from pathlib import Path
from typing import Any

import pytest

from saki_executor.plugins.ipc.client import PluginWorkerClient
from saki_executor.plugins.ipc import protocol
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.steps.workspace import Workspace
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb


@pytest.mark.anyio
async def test_plugin_worker_lifecycle_demo_plugin(tmp_path: Path):
    step_id = "worker-step-1"
    workspace = Workspace(str(tmp_path / "runs"), step_id)
    workspace.ensure()

    event_rows: list[tuple[str, dict[str, Any]]] = []

    async def on_event(event_type: str, payload: dict[str, Any]) -> None:
        event_rows.append((event_type, payload))

    plugins_root = Path(__file__).resolve().parents[2] / "saki-plugins"
    registry = PluginRegistry()
    registry.discover_plugins(plugins_root, auto_sync=True)
    handle = registry.get("demo_det_v1")
    assert handle is not None

    client = PluginWorkerClient(
        plugin_id="demo_det_v1",
        step_id=step_id,
        event_handler=on_event,
        python_executable=handle.python_path,
        entrypoint_module=handle.entrypoint,
    )

    payload_dir = workspace.cache_dir / "ipc_test_payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)
    labels_path = payload_dir / "labels.json"
    samples_path = payload_dir / "samples.json"
    annotations_path = payload_dir / "annotations.json"
    dataset_ir_path = payload_dir / "dataset_ir.pb"
    params_path = payload_dir / "params.json"
    predict_samples_path = payload_dir / "predict_samples.json"
    predict_params_path = payload_dir / "predict_params.json"
    train_result_path = payload_dir / "train_result.json"
    predict_result_path = payload_dir / "predict_result.json"

    protocol.write_json(labels_path, [{"id": "l1", "name": "ship"}])
    protocol.write_json(samples_path, [{"id": "s1"}])
    protocol.write_json(annotations_path, [{"id": "a1", "sample_id": "s1", "category_id": "l1"}])
    protocol.write_json(params_path, {"epochs": 2, "steps_per_epoch": 2, "topk": 2})
    protocol.write_json(predict_samples_path, [{"id": "u1"}, {"id": "u2"}])
    protocol.write_json(predict_params_path, {"topk": 1})
    dataset_ir = irpb.DataBatchIR()
    dataset_ir_path.write_bytes(dataset_ir.SerializeToString())

    try:
        await client.start()
        await client.request(action="ping", payload={})
        await client.request(
            action="prepare_data",
            payload={
                "workspace_root": str(workspace.root),
                "labels_path": str(labels_path),
                "samples_path": str(samples_path),
                "annotations_path": str(annotations_path),
                "dataset_ir_path": str(dataset_ir_path),
            },
        )
        train_reply = await client.request(
            action="train",
            payload={
                "workspace_root": str(workspace.root),
                "params_path": str(params_path),
                "result_path": str(train_result_path),
            },
        )
        assert Path(train_reply.result_path).exists()
        train_payload = protocol.read_json(Path(train_reply.result_path))
        assert isinstance(train_payload, dict)
        assert "metrics" in train_payload

        predict_reply = await client.request(
            action="predict_unlabeled_batch",
            payload={
                "workspace_root": str(workspace.root),
                "samples_path": str(predict_samples_path),
                "strategy": "random_baseline",
                "params_path": str(predict_params_path),
                "result_path": str(predict_result_path),
            },
        )
        predict_payload = protocol.read_json(Path(predict_reply.result_path))
        assert isinstance(predict_payload, dict)
        candidates = predict_payload.get("candidates")
        assert isinstance(candidates, list)
        assert len(candidates) == 1

        await asyncio.sleep(0.05)
        event_types = {item[0] for item in event_rows}
        assert "progress" in event_types
        assert "metric" in event_types
    finally:
        await client.close()
