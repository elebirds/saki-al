import asyncio

import pytest

import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.grpc.runtime_control import (
    RuntimeControlService,
    _RequestDedupCache,
    _RuntimeStreamState,
)
from saki_api.grpc_gen import runtime_control_pb2 as pb


def _build_stream_state() -> _RuntimeStreamState:
    return _RuntimeStreamState(
        outbox=asyncio.Queue(),
        dedup_cache=_RequestDedupCache(ttl_sec=60, max_entries=128),
    )


@pytest.mark.anyio
async def test_handle_stream_register_missing_executor_sets_close_flag(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()
    monkeypatch.setattr(runtime_control_module.settings, "RUNTIME_STREAM_REJECT_CLOSE", True)

    handled = await service._handle_stream_register(  # noqa: SLF001
        message=pb.RuntimeMessage(
            register=pb.Register(
                request_id="register-missing-eid-1",
                executor_id="",
                version="1.0.0",
            )
        ),
        state=state,
    )

    assert handled is False
    assert state.close_stream_after_flush is True
    response = await state.outbox.get()
    assert response.WhichOneof("payload") == "error"
    assert response.error.code == "INVALID_ARGUMENT"
    assert response.error.reply_to == "register-missing-eid-1"


@pytest.mark.anyio
async def test_handle_stream_register_permission_error_keeps_stream_when_reject_close_disabled(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()
    monkeypatch.setattr(runtime_control_module.settings, "RUNTIME_STREAM_REJECT_CLOSE", False)

    async def fake_register(**_kwargs):
        raise PermissionError("executor not allowed")

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register", fake_register)

    handled = await service._handle_stream_register(  # noqa: SLF001
        message=pb.RuntimeMessage(
            register=pb.Register(
                request_id="register-permission-1",
                executor_id="executor-blocked-1",
                version="1.0.0",
            )
        ),
        state=state,
    )

    assert handled is True
    assert state.close_stream_after_flush is False
    response = await state.outbox.get()
    assert response.WhichOneof("payload") == "error"
    assert response.error.code == "FORBIDDEN"
    assert response.error.reason == "executor not allowed"


def test_build_dispatcher_register_kwargs_includes_plugin_capabilities_when_supported(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()

    async def fake_register(
        *,
        executor_id: str,
        queue,
        version: str,
        plugin_ids: set[str],
        resources: dict[str, object],
        plugin_capabilities: list[dict[str, object]],
    ) -> None:
        del executor_id, queue, version, plugin_ids, resources, plugin_capabilities

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register", fake_register)

    kwargs = service._build_dispatcher_register_kwargs(  # noqa: SLF001
        state=state,
        register=pb.Register(
            executor_id="executor-1",
            version="1.0.0",
        ),
        executor_id="executor-1",
        plugin_capabilities=[{"plugin_id": "yolo_det_v1"}],
    )

    assert kwargs["executor_id"] == "executor-1"
    assert kwargs["plugin_ids"] == {"yolo_det_v1"}
    assert "plugin_capabilities" in kwargs


def test_build_dispatcher_register_kwargs_omits_plugin_capabilities_when_not_supported(monkeypatch):
    service = RuntimeControlService()
    state = _build_stream_state()

    async def fake_register(
        *,
        executor_id: str,
        queue,
        version: str,
        plugin_ids: set[str],
        resources: dict[str, object],
    ) -> None:
        del executor_id, queue, version, plugin_ids, resources

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register", fake_register)

    kwargs = service._build_dispatcher_register_kwargs(  # noqa: SLF001
        state=state,
        register=pb.Register(
            executor_id="executor-2",
            version="2.0.0",
        ),
        executor_id="executor-2",
        plugin_capabilities=[{"plugin_id": "fedo_mapper_v1"}],
    )

    assert kwargs["executor_id"] == "executor-2"
    assert kwargs["plugin_ids"] == {"fedo_mapper_v1"}
    assert "plugin_capabilities" not in kwargs
