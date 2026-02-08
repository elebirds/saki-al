import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

import saki_executor.jobs.manager as manager_module
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.manager import JobManager
from saki_executor.plugins.base import ExecutorPlugin, TrainArtifact, TrainOutput
from saki_executor.plugins.registry import PluginRegistry


class _ArtifactPlugin(ExecutorPlugin):
    @property
    def plugin_id(self) -> str:
        return "artifact_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_job_types(self) -> list[str]:
        return ["train_detection"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    def validate_params(self, params: dict[str, Any]) -> None:
        del params

    async def prepare_data(
            self,
            workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
    ) -> None:
        del workspace, labels, samples, annotations

    async def train(self, workspace, params: dict[str, Any], emit) -> TrainOutput:
        del params
        best_path = workspace.artifacts_dir / "best.pt"
        report_path = workspace.artifacts_dir / "report.json"
        optional_path = workspace.artifacts_dir / "confusion_matrix.png"
        best_path.write_bytes(b"best-model")
        report_path.write_text('{"ok": true}', encoding="utf-8")
        optional_path.write_bytes(b"\x89PNG")

        # 插件发出的 artifact 事件应由 manager 忽略。
        await emit(
            "artifact",
            {
                "kind": "weights",
                "name": "plugin-local.bin",
                "uri": str(best_path),
                "meta": {},
            },
        )

        return TrainOutput(
            metrics={"loss": 0.1},
            artifacts=[
                TrainArtifact(
                    kind="weights",
                    name="best.pt",
                    path=best_path,
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
                    kind="confusion_matrix",
                    name="confusion_matrix.png",
                    path=optional_path,
                    content_type="image/png",
                    required=False,
                ),
            ],
        )

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params
        return []

    async def stop(self, job_id: str) -> None:
        del job_id


def _build_manager(tmp_path: Path) -> JobManager:
    registry = PluginRegistry()
    registry.register(_ArtifactPlugin())
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    return JobManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)


def _mock_data_items(query_type: int) -> list[pb.DataItem]:
    if query_type == pb.SAMPLES:
        return [pb.DataItem(sample_item=pb.SampleItem(id="s1"))]
    if query_type == pb.ANNOTATIONS:
        return [pb.DataItem(annotation_item=pb.AnnotationItem(id="a1", sample_id="s1", category_id="c1"))]
    return []


def _make_fake_request(fail_upload_attempts: dict[str, int]):
    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        if payload_type == "data_request":
            request = message.data_request
            return pb.RuntimeMessage(
                data_response=pb.DataResponse(
                    request_id=f"resp-{request.request_id}",
                    reply_to=request.request_id,
                    job_id=request.job_id,
                    query_type=request.query_type,
                    items=_mock_data_items(request.query_type),
                    next_cursor="",
                )
            )
        if payload_type == "upload_ticket_request":
            req = message.upload_ticket_request
            name = str(req.artifact_name)
            upload_url = f"https://upload.local/{name}"
            return pb.RuntimeMessage(
                upload_ticket_response=pb.UploadTicketResponse(
                    request_id=f"upload-{req.request_id}",
                    reply_to=req.request_id,
                    job_id=req.job_id,
                    upload_url=upload_url,
                    storage_uri=f"s3://bucket/runtime/{name}",
                    headers={"x-fail-attempts": str(fail_upload_attempts.get(name, 0))},
                )
            )
        raise AssertionError(f"unexpected request payload: {payload_type}")

    return fake_request


def _install_async_client_mock(monkeypatch):
    state = {
        "attempts": {},
        "uploaded_bytes": {},
    }

    class _AsyncClientMock:
        def __init__(self, timeout: int = 180):
            del timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def put(self, url: str, *, content=None, headers=None):
            if content is None or not hasattr(content, "__aiter__"):
                raise RuntimeError("content must be async iterable")

            data = bytearray()
            async for chunk in content:
                data.extend(chunk)

            headers = headers or {}
            fail_attempts = int(headers.get("x-fail-attempts", "0"))
            state["uploaded_bytes"][url] = bytes(data)
            state["attempts"][url] = state["attempts"].get(url, 0) + 1

            request = httpx.Request("PUT", url)
            if state["attempts"][url] <= fail_attempts:
                return httpx.Response(500, request=request, text="upload failed")
            return httpx.Response(200, request=request, text="ok")

    monkeypatch.setattr(manager_module.httpx, "AsyncClient", _AsyncClientMock)
    return state


@pytest.mark.anyio
async def test_artifact_upload_retries_and_uses_storage_uri(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)
    sent_messages: list[pb.RuntimeMessage] = []
    backoff_calls: list[float] = []
    upload_state = _install_async_client_mock(monkeypatch)

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_sleep(delay: float) -> None:
        backoff_calls.append(delay)

    monkeypatch.setattr(manager_module.asyncio, "sleep", fake_sleep)
    manager.set_transport(fake_send, _make_fake_request({"confusion_matrix.png": 2}))

    accepted = await manager.assign_job(
        "assign-artifact-1",
        {
            "job_id": "job-artifact-1",
            "project_id": "project-1",
            "source_commit_id": "commit-1",
            "plugin_id": "artifact_plugin",
            "mode": "simulation",
            "iteration": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "params": {"simulation_ratio_schedule": [1.0]},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "job_result"]
    assert len(result_messages) == 1
    result = result_messages[0].job_result
    assert result.status == pb.SUCCEEDED

    optional_url = "https://upload.local/confusion_matrix.png"
    assert upload_state["attempts"][optional_url] == 3
    assert backoff_calls == [1.0, 2.0]

    artifact_events = [
        m.job_event for m in sent_messages
        if m.WhichOneof("payload") == "job_event"
        and m.job_event.WhichOneof("event_payload") == "artifact_event"
    ]
    assert {event.artifact_event.artifact.name for event in artifact_events} == {
        "best.pt",
        "report.json",
        "confusion_matrix.png",
    }
    assert all(event.artifact_event.artifact.uri.startswith("s3://") for event in artifact_events)


@pytest.mark.anyio
async def test_optional_artifact_failure_marks_partial_failed(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)
    sent_messages: list[pb.RuntimeMessage] = []
    _install_async_client_mock(monkeypatch)

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(manager_module.asyncio, "sleep", fake_sleep)
    manager.set_transport(fake_send, _make_fake_request({"confusion_matrix.png": 3}))

    accepted = await manager.assign_job(
        "assign-artifact-2",
        {
            "job_id": "job-artifact-2",
            "project_id": "project-1",
            "source_commit_id": "commit-1",
            "plugin_id": "artifact_plugin",
            "mode": "simulation",
            "iteration": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "params": {"simulation_ratio_schedule": [1.0]},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "job_result"]
    assert len(result_messages) == 1
    result = result_messages[0].job_result
    assert result.status == pb.PARTIAL_FAILED
    assert "confusion_matrix.png" in result.error_message
    assert {item.name for item in result.artifacts} == {"best.pt", "report.json"}


@pytest.mark.anyio
async def test_required_artifact_failure_marks_failed(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)
    sent_messages: list[pb.RuntimeMessage] = []
    _install_async_client_mock(monkeypatch)

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(manager_module.asyncio, "sleep", fake_sleep)
    manager.set_transport(fake_send, _make_fake_request({"best.pt": 3}))

    accepted = await manager.assign_job(
        "assign-artifact-3",
        {
            "job_id": "job-artifact-3",
            "project_id": "project-1",
            "source_commit_id": "commit-1",
            "plugin_id": "artifact_plugin",
            "mode": "simulation",
            "iteration": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "params": {"simulation_ratio_schedule": [1.0]},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "job_result"]
    assert len(result_messages) == 1
    result = result_messages[0].job_result
    assert result.status == pb.FAILED
    assert "required artifact upload failed" in result.error_message
