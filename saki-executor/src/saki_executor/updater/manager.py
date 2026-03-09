from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.core.config import settings
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.plugins.venv_manager import ensure_plugin_venv, ensure_plugin_venv_for_profile
from saki_executor.runtime.capability.host_capability_cache import HostCapabilityCache
from saki_executor.updater.launcher_state import (
    load_pending_activation,
    pop_rollback_report,
    write_activation_confirmation,
    write_pending_activation,
)
from saki_plugin_sdk import PluginManifest, evaluate_profile_spec, parse_runtime_profiles

SendFn = Callable[[pb.RuntimeMessage], Awaitable[None]]


class _RollbackApplied(RuntimeError):
    pass


class RuntimeUpdater:
    def __init__(
        self,
        *,
        plugin_registry: PluginRegistry,
        host_capability_cache: HostCapabilityCache,
        shutdown_event: asyncio.Event,
    ) -> None:
        self._plugin_registry = plugin_registry
        self._host_capability_cache = host_capability_cache
        self._shutdown_event = shutdown_event
        self._managed_root = Path(settings.MANAGED_RUNTIME_ROOT).resolve()
        self._state: dict[str, Any] = {}
        self._bootstrap_state_from_pending()

    def _bootstrap_state_from_pending(self) -> None:
        if not bool(settings.MANAGED_RUNTIME_ENABLED):
            self._state = {}
            return
        pending = load_pending_activation(self._managed_root)
        if not pending:
            self._state = {}
            return
        self._state = {
            "request_id": str(pending.get("request_id") or ""),
            "component_type": str(pending.get("component_type") or ""),
            "component_name": str(pending.get("component_name") or ""),
            "from_version": str(pending.get("from_version") or ""),
            "target_version": str(pending.get("target_version") or ""),
            "phase": "activating",
            "detail": "pending activation confirmation",
            "activation_pending": True,
            "rollback_pending": False,
        }

    def build_update_state_snapshot(self) -> dict[str, Any]:
        return dict(self._state)

    def _set_state(
        self,
        *,
        request_id: str,
        component_type: str,
        component_name: str,
        from_version: str,
        target_version: str,
        phase: str,
        detail: str,
        activation_pending: bool = False,
        rollback_pending: bool = False,
    ) -> None:
        self._state = {
            "request_id": str(request_id or ""),
            "component_type": str(component_type or ""),
            "component_name": str(component_name or ""),
            "from_version": str(from_version or ""),
            "target_version": str(target_version or ""),
            "phase": str(phase or ""),
            "detail": str(detail or ""),
            "activation_pending": bool(activation_pending),
            "rollback_pending": bool(rollback_pending),
        }

    @staticmethod
    def _component_type_text(component_type: int) -> str:
        if int(component_type) == int(pb.EXECUTOR):
            return "executor"
        if int(component_type) == int(pb.PLUGIN):
            return "plugin"
        return ""

    def _current_plugin_versions(self) -> dict[str, str]:
        return {
            str(plugin.plugin_id): str(plugin.version)
            for plugin in self._plugin_registry.all()
            if str(getattr(plugin, "plugin_id", "") or "").strip()
        }

    async def emit_startup_runtime_events(self, send_message: SendFn) -> None:
        if not bool(settings.MANAGED_RUNTIME_ENABLED):
            return
        rollback_payload = pop_rollback_report(self._managed_root)
        if rollback_payload:
            await send_message(
                runtime_codec.build_runtime_update_event_message(
                    request_id=str(rollback_payload.get("request_id") or ""),
                    component_type=str(rollback_payload.get("component_type") or ""),
                    component_name=str(rollback_payload.get("component_name") or ""),
                    from_version=str(rollback_payload.get("from_version") or ""),
                    target_version=str(rollback_payload.get("target_version") or ""),
                    phase="rolled_back",
                    detail=str(rollback_payload.get("detail") or "launcher rollback applied"),
                    rolled_back=True,
                )
            )

        pending = load_pending_activation(self._managed_root)
        if not pending:
            return

        actual_executor_version = str(settings.EXECUTOR_VERSION or "")
        actual_plugin_versions = self._current_plugin_versions()
        expected_executor_version = str(pending.get("expected_executor_version") or "")
        expected_plugin_versions = pending.get("expected_plugin_versions") or {}
        if expected_executor_version and actual_executor_version != expected_executor_version:
            return
        if isinstance(expected_plugin_versions, dict):
            for plugin_id, target_version in expected_plugin_versions.items():
                if str(actual_plugin_versions.get(str(plugin_id), "")) != str(target_version or ""):
                    return

        write_activation_confirmation(
            self._managed_root,
            {
                "request_id": str(pending.get("request_id") or ""),
                "executor_version": actual_executor_version,
                "plugin_versions": actual_plugin_versions,
                "confirmed_at": int(time.time()),
            },
        )
        self._set_state(
            request_id=str(pending.get("request_id") or ""),
            component_type=str(pending.get("component_type") or ""),
            component_name=str(pending.get("component_name") or ""),
            from_version=str(pending.get("from_version") or ""),
            target_version=str(pending.get("target_version") or ""),
            phase="succeeded",
            detail="activation confirmed",
        )
        await send_message(
            runtime_codec.build_runtime_update_event_message(
                request_id=str(pending.get("request_id") or ""),
                component_type=str(pending.get("component_type") or ""),
                component_name=str(pending.get("component_name") or ""),
                from_version=str(pending.get("from_version") or ""),
                target_version=str(pending.get("target_version") or ""),
                phase="succeeded",
                detail="activation confirmed",
                rolled_back=False,
            )
        )

    async def process_command(self, command: pb.RuntimeUpdateCommand, send_message: SendFn) -> None:
        component_type = self._component_type_text(command.component_type)
        component_name = str(command.component_name or "")
        from_version = str(command.from_version or "")
        target_version = str(command.target_version or "")
        request_id = str(command.request_id or "")
        if not bool(settings.MANAGED_RUNTIME_ENABLED):
            self._set_state(
                request_id=request_id,
                component_type=component_type,
                component_name=component_name,
                from_version=from_version,
                target_version=target_version,
                phase="failed",
                detail="managed runtime mode is disabled",
            )
            await send_message(
                runtime_codec.build_runtime_update_event_message(
                    request_id=request_id,
                    component_type=component_type,
                    component_name=component_name,
                    from_version=from_version,
                    target_version=target_version,
                    phase="failed",
                    detail="managed runtime mode is disabled",
                    rolled_back=False,
                )
            )
            return

        try:
            self._set_state(
                request_id=request_id,
                component_type=component_type,
                component_name=component_name,
                from_version=from_version,
                target_version=target_version,
                phase="downloading",
                detail="downloading release archive",
            )
            await send_message(
                runtime_codec.build_runtime_update_event_message(
                    request_id=request_id,
                    component_type=component_type,
                    component_name=component_name,
                    from_version=from_version,
                    target_version=target_version,
                    phase="downloading",
                    detail="downloading release archive",
                    rolled_back=False,
                )
            )
            activation_payload = await asyncio.to_thread(self._prepare_update_sync, command)
            self._set_state(
                request_id=request_id,
                component_type=component_type,
                component_name=component_name,
                from_version=from_version,
                target_version=target_version,
                phase="activating",
                detail="activation prepared; restarting child process",
                activation_pending=True,
            )
            await send_message(
                runtime_codec.build_runtime_update_event_message(
                    request_id=request_id,
                    component_type=component_type,
                    component_name=component_name,
                    from_version=from_version,
                    target_version=target_version,
                    phase="activating",
                    detail="activation prepared; restarting child process",
                    rolled_back=False,
                )
            )
            logger.info("runtime update prepared request_id={} payload={}", request_id, activation_payload)
            await asyncio.sleep(0.5)
            self._shutdown_event.set()
        except _RollbackApplied as exc:
            self._set_state(
                request_id=request_id,
                component_type=component_type,
                component_name=component_name,
                from_version=from_version,
                target_version=target_version,
                phase="rolled_back",
                detail=str(exc),
                rollback_pending=True,
            )
            await send_message(
                runtime_codec.build_runtime_update_event_message(
                    request_id=request_id,
                    component_type=component_type,
                    component_name=component_name,
                    from_version=from_version,
                    target_version=target_version,
                    phase="rolled_back",
                    detail=str(exc),
                    rolled_back=True,
                )
            )
        except Exception as exc:
            self._set_state(
                request_id=request_id,
                component_type=component_type,
                component_name=component_name,
                from_version=from_version,
                target_version=target_version,
                phase="failed",
                detail=str(exc),
            )
            await send_message(
                runtime_codec.build_runtime_update_event_message(
                    request_id=request_id,
                    component_type=component_type,
                    component_name=component_name,
                    from_version=from_version,
                    target_version=target_version,
                    phase="failed",
                    detail=str(exc),
                    rolled_back=False,
                )
            )

    def _prepare_update_sync(self, command: pb.RuntimeUpdateCommand) -> dict[str, Any]:
        request_id = str(command.request_id or "")
        component_type = self._component_type_text(command.component_type)
        component_name = str(command.component_name or "")
        target_version = str(command.target_version or "")
        if not str(command.download_url or "").strip():
            raise RuntimeError("download_url is required")

        link_path = Path()
        previous_target = ""
        target_path = Path()
        switched = False
        try:
            target_path = self._download_and_extract_release(command, component_type=component_type)
            if component_type == "plugin":
                self._prevalidate_plugin_release(target_path, component_name=component_name, target_version=target_version)
                link_path = self._managed_root / "plugins" / "active" / component_name
                previous_target = self._resolve_link_target(link_path)
                self._atomic_symlink(target_path, link_path)
                switched = True
                expected_plugin_versions = self._current_plugin_versions()
                expected_plugin_versions[component_name] = target_version
                payload = {
                    "request_id": request_id,
                    "component_type": component_type,
                    "component_name": component_name,
                    "from_version": str(command.from_version or ""),
                    "target_version": target_version,
                    "link_path": str(link_path),
                    "previous_target": previous_target,
                    "target_path": str(target_path),
                    "expected_executor_version": str(settings.EXECUTOR_VERSION or ""),
                    "expected_plugin_versions": expected_plugin_versions,
                    "prepared_at": int(time.time()),
                }
                write_pending_activation(self._managed_root, payload)
                return payload

            if component_type == "executor":
                self._prevalidate_executor_release(target_path, target_version=target_version)
                link_path = self._managed_root / "executor" / "current"
                previous_target = self._resolve_link_target(link_path)
                self._atomic_symlink(target_path, link_path)
                switched = True
                payload = {
                    "request_id": request_id,
                    "component_type": component_type,
                    "component_name": component_name,
                    "from_version": str(command.from_version or ""),
                    "target_version": target_version,
                    "link_path": str(link_path),
                    "previous_target": previous_target,
                    "target_path": str(target_path),
                    "expected_executor_version": target_version,
                    "expected_plugin_versions": self._current_plugin_versions(),
                    "prepared_at": int(time.time()),
                }
                write_pending_activation(self._managed_root, payload)
                return payload

            raise RuntimeError(f"unsupported component_type: {component_type}")
        except Exception as exc:
            if switched:
                self._restore_link(link_path, previous_target)
                raise _RollbackApplied(f"{exc}; activation link restored") from exc
            raise

    def _download_and_extract_release(self, command: pb.RuntimeUpdateCommand, *, component_type: str) -> Path:
        target_version = str(command.target_version or "")
        component_name = str(command.component_name or "")
        if component_type == "plugin":
            release_dir = self._managed_root / "plugins" / component_name / target_version
        else:
            release_dir = self._managed_root / "executor" / "releases" / target_version
        if (release_dir / "pyproject.toml").exists():
            return release_dir

        release_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="saki-runtime-release-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            archive_path = temp_dir / "release.tar.gz"
            self._download_archive(command, archive_path)
            extracted_root = self._extract_archive_to_release_dir(
                archive_path=archive_path,
                release_dir=release_dir,
            )
        return extracted_root

    def _download_archive(self, command: pb.RuntimeUpdateCommand, archive_path: Path) -> None:
        sha256 = hashlib.sha256()
        headers = {str(key): str(value) for key, value in dict(command.headers or {}).items()}
        expected_size = int(command.size_bytes or 0)
        with httpx.Client(timeout=max(60, int(settings.HTTP_TIMEOUT_SEC)), follow_redirects=True) as client:
            with client.stream("GET", str(command.download_url), headers=headers) as response:
                response.raise_for_status()
                total = 0
                with archive_path.open("wb") as output:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        output.write(chunk)
                        sha256.update(chunk)
                        total += len(chunk)
        actual_hash = sha256.hexdigest()
        if str(command.sha256 or "").strip() and actual_hash != str(command.sha256):
            raise RuntimeError(f"sha256 mismatch expected={command.sha256} actual={actual_hash}")
        if expected_size > 0 and int(archive_path.stat().st_size) != expected_size:
            raise RuntimeError(f"size mismatch expected={expected_size} actual={archive_path.stat().st_size}")

    def _extract_archive_to_release_dir(self, *, archive_path: Path, release_dir: Path) -> Path:
        if release_dir.exists():
            return release_dir
        staging_parent = release_dir.parent
        staging_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(staging_parent), prefix=".extract-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            with tarfile.open(archive_path, mode="r:gz") as archive:
                archive.extractall(path=temp_dir)
            project_root = self._resolve_project_root(temp_dir)
            staged_dir = staging_parent / f".{release_dir.name}.{uuid.uuid4().hex}.staging"
            if staged_dir.exists():
                shutil.rmtree(staged_dir)
            shutil.move(str(project_root), str(staged_dir))
            os.replace(staged_dir, release_dir)
        return release_dir

    @staticmethod
    def _resolve_project_root(temp_dir: Path) -> Path:
        direct = temp_dir
        if (direct / "pyproject.toml").exists():
            return direct
        children = [item for item in temp_dir.iterdir() if item.is_dir()]
        if len(children) == 1 and (children[0] / "pyproject.toml").exists():
            return children[0]
        raise RuntimeError("release archive missing pyproject.toml")

    def _prevalidate_plugin_release(self, release_dir: Path, *, component_name: str, target_version: str) -> None:
        manifest = PluginManifest.from_yaml(release_dir / "plugin.yml")
        if str(manifest.plugin_id or "").strip() != component_name:
            raise RuntimeError(
                f"plugin_id mismatch expected={component_name} actual={manifest.plugin_id}"
            )
        if str(manifest.version or "").strip() != target_version:
            raise RuntimeError(
                f"plugin version mismatch expected={target_version} actual={manifest.version}"
            )
        profiles = parse_runtime_profiles(manifest.runtime_profiles)
        if not profiles:
            ensure_plugin_venv(release_dir, auto_sync=True)
            return
        host_snapshot = self._host_capability_cache.get_snapshot()
        matched_profiles = [
            profile
            for profile in profiles
            if evaluate_profile_spec(profile.when, host_capability=host_snapshot)
        ]
        if not matched_profiles:
            raise RuntimeError("no runtime profile matches current host capability")
        for profile in matched_profiles:
            ensure_plugin_venv_for_profile(
                plugin_dir=release_dir,
                plugin_id=component_name,
                plugin_version=target_version,
                profile=profile,
                auto_sync=True,
            )

    @staticmethod
    def _prevalidate_executor_release(release_dir: Path, *, target_version: str) -> None:
        pyproject = tomllib.loads((release_dir / "pyproject.toml").read_text(encoding="utf-8"))
        project_payload = pyproject.get("project") if isinstance(pyproject, dict) else {}
        version = str(project_payload.get("version") or "").strip() if isinstance(project_payload, dict) else ""
        if version != target_version:
            raise RuntimeError(f"executor version mismatch expected={target_version} actual={version}")
        env = dict(os.environ)
        result = subprocess.run(
            ["uv", "sync"],
            cwd=str(release_dir),
            capture_output=True,
            text=True,
            env=env,
            timeout=max(120, int(settings.HTTP_TIMEOUT_SEC)),
            check=False,
        )
        if int(result.returncode or 0) != 0:
            raise RuntimeError(f"uv sync failed: {result.stderr.strip() or result.stdout.strip()}")

    @staticmethod
    def _resolve_link_target(link_path: Path) -> str:
        if not link_path.exists() and not link_path.is_symlink():
            return ""
        try:
            return str(link_path.resolve())
        except Exception:
            return ""

    @staticmethod
    def _atomic_symlink(target_path: Path, link_path: Path) -> None:
        if link_path.exists() and not link_path.is_symlink():
            raise RuntimeError(f"activation path is not a symlink: {link_path}")
        link_path.parent.mkdir(parents=True, exist_ok=True)
        temp_link = link_path.with_name(f".{link_path.name}.{uuid.uuid4().hex}.tmp")
        if temp_link.exists() or temp_link.is_symlink():
            temp_link.unlink(missing_ok=True)
        temp_link.symlink_to(target_path)
        os.replace(temp_link, link_path)

    @staticmethod
    def _restore_link(link_path: Path, previous_target: str) -> None:
        if str(previous_target or "").strip():
            RuntimeUpdater._atomic_symlink(Path(previous_target), link_path)
            return
        link_path.unlink(missing_ok=True)
