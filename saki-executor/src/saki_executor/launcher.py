from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from saki_executor.core.config import settings
from saki_executor.core.logging import setup_logging
from saki_executor.updater.launcher_state import (
    clear_activation_confirmation,
    clear_pending_activation,
    load_activation_confirmation,
    load_pending_activation,
    write_rollback_report,
)


def _managed_root() -> Path:
    return Path(settings.MANAGED_RUNTIME_ROOT).resolve()


def _current_executor_link() -> Path:
    return _managed_root() / "executor" / "current"


def _build_child_command() -> list[str]:
    current_link = _current_executor_link()
    if bool(settings.MANAGED_RUNTIME_ENABLED) and (current_link.exists() or current_link.is_symlink()):
        return [
            "uv",
            "run",
            "--directory",
            str(current_link.resolve()),
            "python",
            "-m",
            "saki_executor.main",
        ]
    return [sys.executable, "-m", "saki_executor.main"]


def _build_child_env() -> dict[str, str]:
    env = dict(os.environ)
    if bool(settings.MANAGED_RUNTIME_ENABLED):
        env["MANAGED_RUNTIME_ENABLED"] = "true"
        env["MANAGED_RUNTIME_ROOT"] = str(_managed_root())
        env["PLUGINS_DIR"] = str(_managed_root() / "plugins" / "active")
    return env


def _confirmation_matches(pending: dict[str, object], confirmation: dict[str, object]) -> bool:
    if str(pending.get("request_id") or "") != str(confirmation.get("request_id") or ""):
        return False
    expected_executor_version = str(pending.get("expected_executor_version") or "")
    if expected_executor_version and str(confirmation.get("executor_version") or "") != expected_executor_version:
        return False
    expected_plugin_versions = pending.get("expected_plugin_versions") or {}
    confirmation_plugins = confirmation.get("plugin_versions") or {}
    if isinstance(expected_plugin_versions, dict) and isinstance(confirmation_plugins, dict):
        for plugin_id, version in expected_plugin_versions.items():
            if str(confirmation_plugins.get(plugin_id) or "") != str(version or ""):
                return False
    return True


def _restore_link(link_path: Path, previous_target: str) -> None:
    if str(previous_target or "").strip():
        temp_link = link_path.with_name(f".{link_path.name}.rollback.tmp")
        if temp_link.exists() or temp_link.is_symlink():
            temp_link.unlink(missing_ok=True)
        temp_link.symlink_to(Path(previous_target))
        os.replace(temp_link, link_path)
        return
    link_path.unlink(missing_ok=True)


def _rollback_pending_activation(reason: str, pending: dict[str, object]) -> None:
    link_path = Path(str(pending.get("link_path") or ""))
    if str(link_path):
        _restore_link(link_path, str(pending.get("previous_target") or ""))
    write_rollback_report(
        _managed_root(),
        {
            "request_id": str(pending.get("request_id") or ""),
            "component_type": str(pending.get("component_type") or ""),
            "component_name": str(pending.get("component_name") or ""),
            "from_version": str(pending.get("from_version") or ""),
            "target_version": str(pending.get("target_version") or ""),
            "detail": reason,
            "rolled_back_at": int(time.time()),
        },
    )
    clear_activation_confirmation(_managed_root())
    clear_pending_activation(_managed_root())


def _monitor_pending_activation(process: subprocess.Popen[bytes], pending: dict[str, object]) -> bool:
    deadline = time.monotonic() + max(30, int(settings.LAUNCHER_ACTIVATION_TIMEOUT_SEC))
    poll_interval = max(0.1, int(settings.LAUNCHER_POLL_INTERVAL_MS) / 1000.0)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _rollback_pending_activation("child exited before activation confirmation", pending)
            return False
        confirmation = load_activation_confirmation(_managed_root())
        if confirmation:
            if _confirmation_matches(pending, confirmation):
                clear_activation_confirmation(_managed_root())
                clear_pending_activation(_managed_root())
                logger.info("activation confirmed request_id={}", pending.get("request_id"))
                return True
            _rollback_pending_activation("activation confirmation inventory mismatch", pending)
            return False
        time.sleep(poll_interval)
    _rollback_pending_activation("activation confirmation timeout", pending)
    return False


def main() -> None:
    setup_logging(
        level=settings.LOG_LEVEL,
        log_dir=settings.LOG_DIR,
        log_file_name=settings.LOG_FILE_NAME,
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
        color_mode=settings.LOG_COLOR_MODE,
    )
    stop_requested = False

    def _handle_signal(signum, _frame) -> None:  # type: ignore[no-untyped-def]
        nonlocal stop_requested
        stop_requested = True
        logger.info("launcher received signal={}", signum)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop_requested:
        pending = load_pending_activation(_managed_root()) if bool(settings.MANAGED_RUNTIME_ENABLED) else None
        command = _build_child_command()
        env = _build_child_env()
        logger.info("launcher starting child command={}", command)
        child = subprocess.Popen(command, env=env)
        if pending and not _monitor_pending_activation(child, pending):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            time.sleep(1)
            continue
        return_code = child.wait()
        logger.warning("child exited return_code={}", return_code)
        if stop_requested:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
