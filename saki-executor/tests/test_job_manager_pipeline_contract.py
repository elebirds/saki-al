import asyncio
from pathlib import Path

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.steps.contracts import ArtifactUploadTicket, FetchedPage, TaskExecutionRequest
from saki_executor.steps.manager import TaskManager
from saki_executor.plugins.registry import PluginRegistry
from runtime_data_test_helper import build_data_response_message


def _build_manager(tmp_path: Path) -> TaskManager:
    registry = PluginRegistry()
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    return TaskManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)


def test_job_execution_request_from_payload_requires_explicit_fields():
    request = TaskExecutionRequest.from_payload(
        {
            "task_id": "step-1",
            "round_id": "round-1",
            "plugin_id": "demo_det_v1",
            "round_index": "2",
            "mode": "simulation",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "query_strategy": "random_baseline",
            "resolved_params": {"topk": 10},
        }
    )
    assert request.round_id == "round-1"
    assert request.plugin_id == "demo_det_v1"
    assert request.mode == "simulation"
    assert request.round_index == 2
    assert request.query_strategy == "random_baseline"


def test_job_execution_request_requires_task_type_and_dispatch_kind():
    with pytest.raises(ValueError, match="task_type is required"):
        TaskExecutionRequest.from_payload(
            {
                "task_id": "step-1",
                "round_id": "round-1",
                "plugin_id": "demo_det_v1",
                "round_index": 1,
                "mode": "simulation",
                "dispatch_kind": "dispatchable",
                "query_strategy": "random_baseline",
            }
        )

    with pytest.raises(ValueError, match="dispatch_kind is required"):
        TaskExecutionRequest.from_payload(
            {
                "task_id": "step-1",
                "round_id": "round-1",
                "plugin_id": "demo_det_v1",
                "round_index": 1,
                "mode": "simulation",
                "task_type": "train",
                "query_strategy": "random_baseline",
            }
        )


def test_predict_task_allows_missing_round_index():
    request = TaskExecutionRequest.from_payload(
        {
            "task_id": "predict-1",
            "round_id": "",
            "plugin_id": "demo_det_v1",
            "mode": "manual",
            "task_type": "predict",
            "dispatch_kind": "dispatchable",
            "resolved_params": {},
        }
    )
    assert request.task_type == "predict"
    assert request.round_index == 0


def test_non_predict_task_still_requires_positive_round_index():
    with pytest.raises(ValueError, match="round_index is required and must be a positive integer"):
        TaskExecutionRequest.from_payload(
            {
                "task_id": "train-1",
                "round_id": "round-1",
                "plugin_id": "demo_det_v1",
                "mode": "simulation",
                "task_type": "train",
                "dispatch_kind": "dispatchable",
                "resolved_params": {},
            }
        )


def test_sampling_params_required_only_for_sampling_steps():
    # train step in AL mode should not require sampling.strategy/topk
    train_request = TaskExecutionRequest.from_payload(
        {
            "task_id": "step-train-1",
            "round_id": "round-1",
            "plugin_id": "demo_det_v1",
            "round_index": 1,
            "mode": "active_learning",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "resolved_params": {},
        }
    )
    assert train_request.task_type == "train"

    # eval step in AL mode should not require sampling.strategy/topk
    eval_request = TaskExecutionRequest.from_payload(
        {
            "task_id": "step-eval-1",
            "round_id": "round-1",
            "plugin_id": "demo_det_v1",
            "round_index": 1,
            "mode": "active_learning",
            "task_type": "eval",
            "dispatch_kind": "dispatchable",
            "resolved_params": {},
        }
    )
    assert eval_request.task_type == "eval"

    # score step in AL mode must still provide sampling.strategy/topk
    with pytest.raises(ValueError, match="sampling.strategy is required for active_learning/simulation"):
        TaskExecutionRequest.from_payload(
            {
                "task_id": "step-score-1",
                "round_id": "round-1",
                "plugin_id": "demo_det_v1",
                "round_index": 1,
                "mode": "active_learning",
                "task_type": "score",
                "dispatch_kind": "dispatchable",
                "resolved_params": {},
            }
        )


@pytest.mark.anyio
async def test_assign_task_passes_typed_request_to_run_step(tmp_path: Path):
    manager = _build_manager(tmp_path)
    captured: list[TaskExecutionRequest] = []

    async def fake_run_step(request: TaskExecutionRequest) -> None:
        captured.append(request)

    manager._run_task = fake_run_step  # type: ignore[method-assign]  # noqa: SLF001
    accepted = await manager.assign_task(
        "req-1",
        {
            "task_id": "step-typed-1",
            "round_id": "round-typed-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": "demo_det_v1",
            "mode": "active_learning",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "query_strategy": "uncertainty_1_minus_max_conf",
            "round_index": 1,
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=1)  # noqa: SLF001
    assert len(captured) == 1
    assert isinstance(captured[0], TaskExecutionRequest)
    assert captured[0].task_id == "step-typed-1"
    assert captured[0].round_id == "round-typed-1"


@pytest.mark.anyio
async def test_fetch_page_and_upload_ticket_are_typed_contracts(tmp_path: Path):
    manager = _build_manager(tmp_path)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        if payload_type == "data_request":
            req = message.data_request
            return build_data_response_message(
                request_id=f"resp-{req.request_id}",
                reply_to=req.request_id,
                task_id=req.task_id,
                query_type=req.query_type,
                items=[pb.DataItem(sample_item=pb.SampleItem(id="sample-1"))],
            )
        if payload_type == "upload_ticket_request":
            req = message.upload_ticket_request
            return pb.RuntimeMessage(
                upload_ticket_response=pb.UploadTicketResponse(
                    request_id=f"resp-{req.request_id}",
                    reply_to=req.request_id,
                    task_id=req.task_id,
                    upload_url="https://upload.local/test.bin",
                    storage_uri="s3://bucket/test.bin",
                    headers={"x-test": "1"},
                )
            )
        raise AssertionError(f"unexpected payload_type={payload_type}")

    async def fake_send(message: pb.RuntimeMessage) -> None:
        del message
        return

    manager.set_transport(fake_send, fake_request)
    page = await manager._fetch_page(  # noqa: SLF001
        task_id="step-1",
        query_type="samples",
        project_id="project-1",
        commit_id="commit-1",
        cursor=None,
        limit=10,
    )
    assert isinstance(page, FetchedPage)
    assert page.items and page.items[0]["id"] == "sample-1"

    ticket = await manager._request_upload_ticket(  # noqa: SLF001
        task_id="step-1",
        artifact_name="test.bin",
        content_type="application/octet-stream",
    )
    assert isinstance(ticket, ArtifactUploadTicket)
    assert ticket.storage_uri == "s3://bucket/test.bin"
