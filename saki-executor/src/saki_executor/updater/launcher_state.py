from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def launcher_state_dir(root_dir: Path) -> Path:
    path = Path(root_dir) / "launcher"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_activation_path(root_dir: Path) -> Path:
    return launcher_state_dir(root_dir) / "pending-activation.json"


def activation_confirmation_path(root_dir: Path) -> Path:
    return launcher_state_dir(root_dir) / "activation-confirmation.json"


def rollback_report_path(root_dir: Path) -> Path:
    return launcher_state_dir(root_dir) / "rollback-report.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, path)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _clear_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        return


def write_pending_activation(root_dir: Path, payload: dict[str, Any]) -> None:
    _write_json_atomic(pending_activation_path(root_dir), payload)


def load_pending_activation(root_dir: Path) -> dict[str, Any] | None:
    return _load_json(pending_activation_path(root_dir))


def clear_pending_activation(root_dir: Path) -> None:
    _clear_file(pending_activation_path(root_dir))


def write_activation_confirmation(root_dir: Path, payload: dict[str, Any]) -> None:
    _write_json_atomic(activation_confirmation_path(root_dir), payload)


def load_activation_confirmation(root_dir: Path) -> dict[str, Any] | None:
    return _load_json(activation_confirmation_path(root_dir))


def clear_activation_confirmation(root_dir: Path) -> None:
    _clear_file(activation_confirmation_path(root_dir))


def write_rollback_report(root_dir: Path, payload: dict[str, Any]) -> None:
    _write_json_atomic(rollback_report_path(root_dir), payload)


def pop_rollback_report(root_dir: Path) -> dict[str, Any] | None:
    path = rollback_report_path(root_dir)
    payload = _load_json(path)
    _clear_file(path)
    return payload
