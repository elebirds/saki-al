from __future__ import annotations

import socket

from saki_executor.core.config import Settings


def _expected_default_executor_id() -> str:
    hostname = str(socket.gethostname() or "").strip()
    return hostname or "executor-1"


def test_settings_executor_id_defaults_to_hostname(monkeypatch) -> None:
    monkeypatch.delenv("EXECUTOR_ID", raising=False)

    settings = Settings(_env_file=None)

    assert settings.EXECUTOR_ID == _expected_default_executor_id()


def test_settings_executor_id_empty_env_fallbacks_to_hostname(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTOR_ID", "")

    settings = Settings(_env_file=None)

    assert settings.EXECUTOR_ID == _expected_default_executor_id()


def test_settings_executor_id_respects_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTOR_ID", "executor-custom")

    settings = Settings(_env_file=None)

    assert settings.EXECUTOR_ID == "executor-custom"

