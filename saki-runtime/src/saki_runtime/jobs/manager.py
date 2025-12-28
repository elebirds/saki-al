import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import portalocker
from loguru import logger

from saki_runtime.core.config import settings
from saki_runtime.core.exceptions import conflict, not_found, invalid_argument
from saki_runtime.jobs.interfaces import JobRunner, PluginAdapter
from saki_runtime.jobs.state import JobStateMachine
from saki_runtime.jobs.workspace import Workspace
from saki_runtime.schemas.enums import EventType, JobStatus
from saki_runtime.schemas.events import (
    ArtifactPayload,
    EventEnvelope,
    MetricPayload,
    StatusPayload,
)
from saki_runtime.schemas.jobs import (
    JobCreateRequest,
    JobCreateResponse,
    JobInfo,
    JobResources,
)


class GPULockManager:
    def __init__(self, lock_dir: Path):
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._files: Dict[int, Any] = {}

    def acquire(self, gpu_id: int) -> bool:
        # Ensure lock dir exists in case it was removed (e.g. by tests)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        
        lock_file = self.lock_dir / f"gpu{gpu_id}.lock"
        try:
            f = open(lock_file, "w")
            portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
            self._files[gpu_id] = f
            return True
        except (portalocker.LockException, OSError) as e:
            # If it's an OSError other than "file in use" (which portalocker handles via LockException usually, 
            # but on Windows locking might raise OSError/PermissionError), we should log it.
            # But here we just return False to indicate failure to acquire.
            if gpu_id in self._files:
                # Already held by this process
                return True
            return False

    def release(self, gpu_id: int) -> None:
        if gpu_id in self._files:
            f = self._files.pop(gpu_id)
            try:
                portalocker.unlock(f)
                f.close()
            except Exception as e:
                logger.error(f"Error releasing GPU lock {gpu_id}: {e}")

    def release_all(self) -> None:
        """Release all held locks. Useful for cleanup/testing."""
        for gpu_id in list(self._files.keys()):
            self.release(gpu_id)


class JobManager:
    def __init__(self, runner: JobRunner, plugins: Dict[str, PluginAdapter]):
        self.runner = runner
        self.plugins = plugins
        self.runs_dir = Path(settings.RUNS_DIR)
        self.gpu_locks = GPULockManager(self.runs_dir / "locks")

    def _get_workspace(self, job_id: str) -> Workspace:
        return Workspace(str(self.runs_dir), job_id)

    def _reconstruct_job_state(self, job_id: str) -> JobInfo:
        ws = self._get_workspace(job_id)
        config = ws.load_config()
        if not config:
            raise not_found(f"Job {job_id} not found")

        # Reconstruct from config (static)
        # We need to convert dict back to models to ensure type safety if needed,
        # or just use the dict if it matches the schema.
        # JobInfo requires specific fields.
        
        # Initial state
        info = JobInfo(
            job_id=job_id,
            job_type=config["job_type"],
            plugin_id=config["plugin_id"],
            status=JobStatus.CREATED,
            created_at=0, # Will be updated from events
            data_ref=config["data_ref"],
            params=config["params"],
            resources=config["resources"],
        )

        # Replay events
        store = ws.get_event_store()
        metrics_summary = {}
        
        for event in store.tail(0):
            if event.type == EventType.STATUS:
                payload = StatusPayload.model_validate(event.payload)
                info.status = payload.current_status
                if payload.current_status == JobStatus.CREATED:
                    info.created_at = event.ts
                elif payload.current_status == JobStatus.RUNNING:
                    info.started_at = event.ts
                elif JobStateMachine.is_terminal(payload.current_status):
                    info.ended_at = event.ts
            elif event.type == EventType.METRIC:
                # Keep latest metrics as summary
                payload = MetricPayload.model_validate(event.payload)
                metrics_summary.update(payload.metrics)

        if metrics_summary:
            info.summary = metrics_summary

        return info

    async def create_job(self, request: JobCreateRequest) -> JobCreateResponse:
        # 1. Validate Plugin
        if request.plugin_id not in self.plugins:
            raise invalid_argument(f"Plugin {request.plugin_id} not found")
        
        plugin = self.plugins[request.plugin_id]
        
        # 2. Validate Params
        try:
            plugin.validate_params(request.params)
        except Exception as e:
            raise invalid_argument(f"Invalid params for plugin {request.plugin_id}: {e}")

        # 3. Create Workspace
        job_id = str(uuid.uuid4())
        ws = self._get_workspace(job_id)
        ws.ensure_created()
        
        # Write config
        ws.write_config(request.model_dump(mode="json"))

        # 4. Write Created Event
        event = EventEnvelope(
            job_id=job_id,
            seq=ws.get_event_store().next_seq(),
            ts=int(time.time()),
            type=EventType.STATUS,
            payload=StatusPayload(
                previous_status=JobStatus.CREATED, # Initial
                current_status=JobStatus.CREATED,
                message="Job created"
            ).model_dump()
        )
        ws.get_event_store().append(event)

        return JobCreateResponse(
            request_id=str(uuid.uuid4()),
            job_id=job_id,
            status=JobStatus.CREATED
        )

    async def start_job(self, job_id: str) -> None:
        info = self._reconstruct_job_state(job_id)
        
        # Idempotency
        if info.status == JobStatus.RUNNING:
            return
        
        # Validate transition
        if not JobStateMachine.can_transition(info.status, JobStatus.RUNNING):
            raise conflict(f"Cannot start job in state {info.status}")

        ws = self._get_workspace(job_id)
        plugin = self.plugins[info.plugin_id]

        # Acquire GPU Lock
        # MVP: Only support 1 GPU, device_ids[0]
        gpu_id = info.resources.gpu.device_ids[0]
        if not self.gpu_locks.acquire(gpu_id):
            raise conflict(f"GPU {gpu_id} is currently in use")

        try:
            # Prepare (Fetch IR)
            await plugin.prepare(ws, info.params)

            # Start Runner
            await self.runner.start_train(ws, gpu_id)

            # Write Running Event
            event = EventEnvelope(
                job_id=job_id,
                seq=ws.get_event_store().next_seq(),
                ts=int(time.time()),
                type=EventType.STATUS,
                payload=StatusPayload(
                    previous_status=info.status,
                    current_status=JobStatus.RUNNING,
                    message="Job started"
                ).model_dump()
            )
            ws.get_event_store().append(event)

        except Exception as e:
            logger.error(f"Failed to start job {job_id}: {e}")
            self.gpu_locks.release(gpu_id)
            # Write Failed Event
            event = EventEnvelope(
                job_id=job_id,
                seq=ws.get_event_store().next_seq(),
                ts=int(time.time()),
                type=EventType.STATUS,
                payload=StatusPayload(
                    previous_status=info.status,
                    current_status=JobStatus.FAILED,
                    message=f"Failed to start: {str(e)}"
                ).model_dump()
            )
            ws.get_event_store().append(event)
            raise

    async def stop_job(self, job_id: str) -> None:
        info = self._reconstruct_job_state(job_id)
        
        # Idempotency
        if JobStateMachine.is_terminal(info.status):
            return

        ws = self._get_workspace(job_id)

        # Write Stopping Event
        event = EventEnvelope(
            job_id=job_id,
            seq=ws.get_event_store().next_seq(),
            ts=int(time.time()),
            type=EventType.STATUS,
            payload=StatusPayload(
                previous_status=info.status,
                current_status=JobStatus.STOPPING,
                message="Job stopping"
            ).model_dump()
        )
        ws.get_event_store().append(event)

        try:
            await self.runner.stop(job_id)
        except Exception as e:
            logger.error(f"Error stopping runner for job {job_id}: {e}")

        # Release GPU Lock
        gpu_id = info.resources.gpu.device_ids[0]
        self.gpu_locks.release(gpu_id)

        # Write Stopped Event
        event = EventEnvelope(
            job_id=job_id,
            seq=ws.get_event_store().next_seq(),
            ts=int(time.time()),
            type=EventType.STATUS,
            payload=StatusPayload(
                previous_status=JobStatus.STOPPING,
                current_status=JobStatus.STOPPED,
                message="Job stopped by user"
            ).model_dump()
        )
        ws.get_event_store().append(event)

    def get_job(self, job_id: str) -> JobInfo:
        return self._reconstruct_job_state(job_id)

    def get_job_metrics(self, job_id: str) -> List[Dict[str, Any]]:
        ws = self._get_workspace(job_id)
        if not ws.config_path.exists():
            raise not_found(f"Job {job_id} not found")
            
        metrics = []
        for event in ws.get_event_store().tail(0):
            if event.type == EventType.METRIC:
                metrics.append(event.payload)
        return metrics

    def list_artifacts(self, job_id: str) -> List[ArtifactPayload]:
        ws = self._get_workspace(job_id)
        if not ws.config_path.exists():
            raise not_found(f"Job {job_id} not found")

        artifacts = []
        
        # 1. System artifacts
        if ws.config_path.exists():
            artifacts.append(ArtifactPayload(
                name="config.json",
                path=ws.config_path.resolve().as_uri(),
                type="config",
                size_bytes=ws.config_path.stat().st_size
            ))
        
        if ws.events_path.exists():
            artifacts.append(ArtifactPayload(
                name="events.jsonl",
                path=ws.events_path.resolve().as_uri(),
                type="events",
                size_bytes=ws.events_path.stat().st_size
            ))

        # 2. Generated artifacts
        if ws.artifacts_dir.exists():
            for p in ws.artifacts_dir.rglob("*"):
                if p.is_file():
                    artifacts.append(ArtifactPayload(
                        name=p.name,
                        path=p.resolve().as_uri(),
                        type="artifact",
                        size_bytes=p.stat().st_size
                    ))
        
        return artifacts
