import asyncio
from pathlib import Path
from typing import Any

import pytest

from saki_executor.plugins.ipc.client import PluginWorkerClient
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.plugins.venv_manager import ensure_plugin_venv_for_profile
from saki_executor.steps.workspace import Workspace
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb
from saki_plugin_sdk import (
    DeviceBinding,
    ExecutionBindingContext,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    TaskRuntimeContext,
)
from saki_plugin_sdk.ipc import protocol


@pytest.mark.anyio
async def test_plugin_worker_lifecycle_demo_plugin(tmp_path: Path):
    task_id = "worker-step-1"
    workspace = Workspace(str(tmp_path / "runs"), task_id)
    workspace.ensure()

    event_rows: list[tuple[str, dict[str, Any]]] = []

    async def on_event(event_type: str, payload: dict[str, Any]) -> None:
        event_rows.append((event_type, payload))

    plugins_root = Path(__file__).resolve().parents[2] / "saki-plugins"
    registry = PluginRegistry()
    registry.discover_plugins(plugins_root)
    handle = registry.get("demo_det_v1")
    assert handle is not None
    profile = handle.runtime_profiles[0]
    worker_python = ensure_plugin_venv_for_profile(
        plugin_dir=handle.plugin_dir,
        plugin_id=handle.plugin_id,
        plugin_version=handle.version,
        profile=profile,
        auto_sync=True,
    )

    client = PluginWorkerClient(
        plugin_id="demo_det_v1",
        task_id=task_id,
        event_handler=on_event,
        python_executable=worker_python,
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
    runtime_capability_path = payload_dir / "runtime_capability.json"
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
    runtime_context = TaskRuntimeContext(
        task_id=task_id,
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="simulation",
        split_seed=1,
        train_seed=2,
        sampling_seed=3,
        resolved_device_backend="cpu",
    )
    execution_context = ExecutionBindingContext(
        task_context=runtime_context,
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 8192,
                "gpus": [],
                "metal_available": False,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            }
        ),
        runtime_capability=RuntimeCapabilitySnapshot(
            framework="demo",
            framework_version="",
            backends=["cpu"],
            backend_details={},
            errors=[],
        ),
        device_binding=DeviceBinding(
            backend="cpu",
            device_spec="cpu",
            precision="fp32",
            profile_id="cpu",
            reason="test",
            fallback_applied=False,
        ),
        profile_id="cpu",
    )

    try:
        await client.start()
        await client.request(action="ping", payload={})
        runtime_reply = await client.request(
            action="probe_runtime_capability",
            payload={"result_path": str(runtime_capability_path)},
            runtime_context=runtime_context,
        )
        runtime_payload = protocol.read_json(Path(runtime_reply.result_path))
        runtime_capability = protocol.parse_runtime_capability(runtime_payload)
        execution_context = ExecutionBindingContext(
            task_context=runtime_context,
            host_capability=execution_context.host_capability,
            runtime_capability=runtime_capability,
            device_binding=execution_context.device_binding,
            profile_id="cpu",
        )
        await client.request(
            action="bind_execution_context",
            payload={},
            execution_binding_context=execution_context,
        )
        await client.request(
            action="prepare_data",
            payload={
                "workspace_root": str(workspace.root),
                "labels_path": str(labels_path),
                "samples_path": str(samples_path),
                "annotations_path": str(annotations_path),
                "dataset_ir_path": str(dataset_ir_path),
            },
            execution_binding_context=execution_context,
        )
        train_reply = await client.request(
            action="train",
            payload={
                "workspace_root": str(workspace.root),
                "params_path": str(params_path),
                "result_path": str(train_result_path),
            },
            execution_binding_context=execution_context,
        )
        assert Path(train_reply.result_path).exists()
        train_payload = protocol.read_json(Path(train_reply.result_path))
        assert isinstance(train_payload, dict)
        assert "metrics" in train_payload
        metrics = train_payload.get("metrics")
        assert isinstance(metrics, dict)
        assert set(metrics.keys()) == {"map50", "map50_95", "precision", "recall", "loss"}

        artifacts = train_payload.get("artifacts")
        assert isinstance(artifacts, list)
        report_artifact = next((item for item in artifacts if item.get("name") == "report.json"), None)
        assert isinstance(report_artifact, dict)
        report_path = Path(str(report_artifact.get("path") or ""))
        assert report_path.exists()
        report_payload = protocol.read_json(report_path)
        assert report_payload.get("meta", {}).get("context_task_type") == "train"
        assert report_payload.get("meta", {}).get("context_mode") == "simulation"
        assert float(report_payload.get("meta", {}).get("context_train_seed") or 0) == 2.0

        predict_reply = await client.request(
            action="predict_unlabeled_batch",
            payload={
                "workspace_root": str(workspace.root),
                "samples_path": str(predict_samples_path),
                "strategy": "random_baseline",
                "params_path": str(predict_params_path),
                "result_path": str(predict_result_path),
            },
            execution_binding_context=execution_context,
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
