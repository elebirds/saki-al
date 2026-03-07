from __future__ import annotations

import pytest

from saki_api.modules.system import app_module


class _SessionStub:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def commit(self) -> None:
        self._calls.append("commit")


class _SessionContext:
    def __init__(self, session: _SessionStub) -> None:
        self._session = session

    async def __aenter__(self) -> _SessionStub:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.anyio
async def test_startup_syncs_presets_when_system_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    session = _SessionStub(calls)

    monkeypatch.setattr(app_module, "SessionLocal", lambda: _SessionContext(session))

    class _FakeSystemSettingsService:
        def __init__(self, received_session: _SessionStub) -> None:
            assert received_session is session

        async def bootstrap_defaults(self) -> None:
            calls.append("bootstrap_defaults")

    class _FakeSystemService:
        def __init__(self, received_session: _SessionStub) -> None:
            assert received_session is session

        async def is_init(self) -> bool:
            calls.append("is_init")
            return True

    async def _fake_init_preset_roles(received_session: _SessionStub) -> None:
        assert received_session is session
        calls.append("init_preset_roles")

    class _FakeScheduler:
        async def start(self) -> None:
            calls.append("gc_start")

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(app_module, "SystemSettingsService", _FakeSystemSettingsService)
    monkeypatch.setattr(app_module, "SystemService", _FakeSystemService)
    monkeypatch.setattr(app_module, "init_preset_roles", _fake_init_preset_roles)
    monkeypatch.setattr(app_module, "asset_gc_scheduler", _FakeScheduler())

    await app_module.SystemAppModule().startup()

    assert calls == [
        "bootstrap_defaults",
        "is_init",
        "init_preset_roles",
        "commit",
        "gc_start",
    ]


@pytest.mark.anyio
async def test_startup_skips_preset_sync_when_system_not_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    session = _SessionStub(calls)

    monkeypatch.setattr(app_module, "SessionLocal", lambda: _SessionContext(session))

    class _FakeSystemSettingsService:
        def __init__(self, received_session: _SessionStub) -> None:
            assert received_session is session

        async def bootstrap_defaults(self) -> None:
            calls.append("bootstrap_defaults")

    class _FakeSystemService:
        def __init__(self, received_session: _SessionStub) -> None:
            assert received_session is session

        async def is_init(self) -> bool:
            calls.append("is_init")
            return False

    async def _fake_init_preset_roles(received_session: _SessionStub) -> None:
        assert received_session is session
        calls.append("init_preset_roles")

    class _FakeScheduler:
        async def start(self) -> None:
            calls.append("gc_start")

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(app_module, "SystemSettingsService", _FakeSystemSettingsService)
    monkeypatch.setattr(app_module, "SystemService", _FakeSystemService)
    monkeypatch.setattr(app_module, "init_preset_roles", _fake_init_preset_roles)
    monkeypatch.setattr(app_module, "asset_gc_scheduler", _FakeScheduler())

    await app_module.SystemAppModule().startup()

    assert calls == [
        "bootstrap_defaults",
        "is_init",
        "gc_start",
    ]
