import asyncio
from pathlib import Path

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.contracts import ArtifactUploadTicket, FetchedPage, JobExecutionRequest
from saki_executor.jobs.manager import JobManager
from saki_executor.plugins.registry import PluginRegistry


def _build_manager(tmp_path: Path) -> JobManager:
    registry = PluginRegistry()
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    return JobManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)


def test_job_execution_request_from_payload_requires_explicit_fields():
    request = JobExecutionRequest.from_payload(
        {
            "task_id": "task-1",
            "job_id": "job-1",
            "plugin_id": "demo_det_v1",
            "round_index": "2",
            "mode": "simulation",
            "query_strategy": "random_baseline",
            "params": {"topk": 10},
        }
    )
    assert request.job_id == "job-1"
    assert request.plugin_id == "demo_det_v1"
    assert request.mode == "simulation"
    assert request.round_index == 2
    assert request.query_strategy == "random_baseline"


@pytest.mark.anyio
async def test_assign_task_passes_typed_request_to_run_task(tmp_path: Path):
    manager = _build_manager(tmp_path)
    captured: list[JobExecutionRequest] = []

    async def fake_run_job(request: JobExecutionRequest) -> None:
        captured.append(request)

    manager._run_task = fake_run_job  # type: ignore[method-assign]  # noqa: SLF001
    accepted = await manager.assign_task(
        "req-1",
        {
            "task_id": "task-typed-1",
            "job_id": "job-typed-1",
            "project_id": "project-1",
            "source_commit_id": "commit-1",
            "plugin_id": "demo_det_v1",
            "mode": "active_learning",
            "query_strategy": "uncertainty_1_minus_max_conf",
            "round_index": 1,
            "params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=1)  # noqa: SLF001
    assert len(captured) == 1
    assert isinstance(captured[0], JobExecutionRequest)
    assert captured[0].task_id == "task-typed-1"
    assert captured[0].job_id == "job-typed-1"


@pytest.mark.anyio
async def test_fetch_page_and_upload_ticket_are_typed_contracts(tmp_path: Path):
    manager = _build_manager(tmp_path)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        if payload_type == "data_request":
            req = message.data_request
            return pb.RuntimeMessage(
                data_response=pb.DataResponse(
                    request_id=f"resp-{req.request_id}",
                    reply_to=req.request_id,
                    task_id=req.task_id,
                    query_type=req.query_type,
                    items=[pb.DataItem(sample_item=pb.SampleItem(id="sample-1"))],
                    next_cursor="",
                )
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
        task_id="task-1",
        query_type="samples",
        project_id="project-1",
        commit_id="commit-1",
        cursor=None,
        limit=10,
    )
    assert isinstance(page, FetchedPage)
    assert page.items and page.items[0]["id"] == "sample-1"

    ticket = await manager._request_upload_ticket(  # noqa: SLF001
        task_id="task-1",
        artifact_name="test.bin",
        content_type="application/octet-stream",
    )
    assert isinstance(ticket, ArtifactUploadTicket)
    assert ticket.storage_uri == "s3://bucket/test.bin"
