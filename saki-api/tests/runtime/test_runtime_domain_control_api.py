from __future__ import annotations

import uuid

import pytest

from saki_api.core.exceptions import InternalServerErrorAppException
from saki_api.modules.runtime.api.http import runtime as runtime_endpoint
from saki_api.modules.runtime.api.runtime_executor import (
    RuntimeDomainCommandResponse,
    RuntimeDomainStatusResponse,
)


class _FakeRuntimeObservabilityService:
    def __init__(self) -> None:
        self.enabled_values: list[bool] = []
        self.reconnect_called = 0

    async def get_runtime_domain_status(self) -> RuntimeDomainStatusResponse:
        return RuntimeDomainStatusResponse(
            configured=True,
            enabled=True,
            state="ready",
            target="127.0.0.1:50051",
            consecutive_failures=0,
            last_error="",
        )

    async def set_runtime_domain_enabled(self, enabled: bool) -> RuntimeDomainCommandResponse:
        self.enabled_values.append(bool(enabled))
        return RuntimeDomainCommandResponse(
            command_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            status="applied",
            message="ok",
        )

    async def reconnect_runtime_domain(self) -> RuntimeDomainCommandResponse:
        self.reconnect_called += 1
        return RuntimeDomainCommandResponse(
            command_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            status="applied",
            message="ok",
        )


@pytest.mark.anyio
async def test_runtime_domain_status_endpoint(monkeypatch):
    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    fake_service = _FakeRuntimeObservabilityService()

    monkeypatch.setattr(runtime_endpoint, "_ensure_runtime_manage_permission", _allow)
    monkeypatch.setattr(
        runtime_endpoint,
        "_resolve_runtime_observability_service",
        lambda **kwargs: fake_service,
    )

    response = await runtime_endpoint.get_runtime_domain_status(
        session=None,
        runtime_observability_service=object(),
        current_user_id=uuid.uuid4(),
    )

    assert response.state == "ready"
    assert response.enabled is True


@pytest.mark.anyio
async def test_runtime_domain_control_endpoints(monkeypatch):
    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    fake_service = _FakeRuntimeObservabilityService()

    monkeypatch.setattr(runtime_endpoint, "_ensure_runtime_manage_permission", _allow)
    monkeypatch.setattr(
        runtime_endpoint,
        "_resolve_runtime_observability_service",
        lambda **kwargs: fake_service,
    )

    connect_resp = await runtime_endpoint.connect_runtime_domain(
        session=None,
        runtime_observability_service=object(),
        current_user_id=uuid.uuid4(),
    )
    disconnect_resp = await runtime_endpoint.disconnect_runtime_domain(
        session=None,
        runtime_observability_service=object(),
        current_user_id=uuid.uuid4(),
    )
    reconnect_resp = await runtime_endpoint.reconnect_runtime_domain(
        session=None,
        runtime_observability_service=object(),
        current_user_id=uuid.uuid4(),
    )

    assert connect_resp.status == "applied"
    assert disconnect_resp.status == "applied"
    assert reconnect_resp.status == "applied"
    assert fake_service.enabled_values == [True, False]
    assert fake_service.reconnect_called == 1


@pytest.mark.anyio
async def test_runtime_domain_connect_endpoint_maps_runtime_error(monkeypatch):
    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    class _FailingService:
        async def set_runtime_domain_enabled(self, enabled: bool) -> RuntimeDomainCommandResponse:
            del enabled
            raise RuntimeError("dispatcher_admin 未配置")

    monkeypatch.setattr(runtime_endpoint, "_ensure_runtime_manage_permission", _allow)
    monkeypatch.setattr(
        runtime_endpoint,
        "_resolve_runtime_observability_service",
        lambda **kwargs: _FailingService(),
    )

    with pytest.raises(InternalServerErrorAppException) as exc_info:
        await runtime_endpoint.connect_runtime_domain(
            session=None,
            runtime_observability_service=object(),
            current_user_id=uuid.uuid4(),
        )
    assert "dispatcher_admin 未配置" in exc_info.value.message
