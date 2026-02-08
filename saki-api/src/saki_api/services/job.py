"""
Job Service - Business logic for L3 runtime jobs.
"""

import uuid
from datetime import timedelta
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.db.transaction import transactional
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l2.branch import Branch
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_event import JobEvent
from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.models.l3.loop import ALLoop
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.repositories.job import JobRepository
from saki_api.repositories.job_event import JobEventRepository
from saki_api.repositories.job_metric_point import JobMetricPointRepository
from saki_api.repositories.loop import LoopRepository
from saki_api.schemas.l3.job import JobCreateRequest, LoopCreateRequest, LoopUpdateRequest
from saki_api.services.loop_config import (
    normalize_loop_global_config,
    merge_model_request_config,
)
from saki_api.services.runtime_plugin_catalog import extract_executor_plugins
from saki_api.services.base import BaseService
from saki_api.utils.storage import get_storage_provider


class JobService(BaseService[Job, JobRepository, JobCreateRequest, JobCreateRequest]):
    """Service for runtime Job lifecycle and read APIs."""

    def __init__(self, session: AsyncSession):
        super().__init__(Job, JobRepository, session)
        self.session = session
        self.loop_repo = LoopRepository(session)
        self.job_event_repo = JobEventRepository(session)
        self.job_metric_repo = JobMetricPointRepository(session)
        self.storage = get_storage_provider()

    @staticmethod
    def _is_downloadable_uri(uri: str | None) -> bool:
        raw = str(uri or "").strip()
        return raw.startswith("s3://") or raw.startswith("http://") or raw.startswith("https://")

    @transactional
    async def create_job_for_loop(self, loop_id: uuid.UUID, payload: JobCreateRequest) -> Job:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        if loop.project_id != payload.project_id:
            raise BadRequestAppException("Loop project_id and request.project_id mismatch")

        await self._validate_plugin_id(payload.plugin_id)

        loop.current_iteration += 1
        self.session.add(loop)

        job = Job(
            project_id=payload.project_id,
            loop_id=loop_id,
            iteration=loop.current_iteration,
            round_index=loop.current_iteration,
            status=TrainingJobStatus.PENDING,
            source_commit_id=payload.source_commit_id,
            job_type=payload.job_type,
            plugin_id=payload.plugin_id,
            mode=payload.mode,
            query_strategy=payload.query_strategy,
            params=payload.params,
            resources=payload.resources,
            strategy_params=payload.strategy_params,
            metrics={},
            artifacts={},
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    @transactional
    async def create_loop(self, project_id: uuid.UUID, payload: LoopCreateRequest) -> ALLoop:
        branch = await self.session.get(Branch, payload.branch_id)
        if not branch:
            raise NotFoundAppException(f"Branch {payload.branch_id} not found")
        if branch.project_id != project_id:
            raise BadRequestAppException("Branch does not belong to this project")

        await self._validate_plugin_id(payload.model_arch)

        existing_loop = await self.loop_repo.get_one(filters=[ALLoop.branch_id == payload.branch_id])
        if existing_loop:
            raise BadRequestAppException("Branch already has a loop bound")

        normalized_global_config = normalize_loop_global_config(payload.global_config)
        normalized_global_config = merge_model_request_config(
            normalized_global_config,
            payload.model_request_config,
        )

        loop = ALLoop(
            project_id=project_id,
            branch_id=payload.branch_id,
            name=payload.name,
            query_strategy=payload.query_strategy,
            model_arch=payload.model_arch,
            global_config=normalized_global_config,
            current_iteration=0,
            is_active=payload.is_active,
            status=payload.status,
            max_rounds=payload.max_rounds,
            query_batch_size=payload.query_batch_size,
            min_seed_labeled=payload.min_seed_labeled,
            min_new_labels_per_round=payload.min_new_labels_per_round,
            stop_patience_rounds=payload.stop_patience_rounds,
            stop_min_gain=payload.stop_min_gain,
            auto_register_model=payload.auto_register_model,
        )
        self.session.add(loop)
        await self.session.flush()
        await self.session.refresh(loop)
        return loop

    @transactional
    async def update_loop(self, loop_id: uuid.UUID, payload: LoopUpdateRequest) -> ALLoop:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")

        if payload.name is not None:
            loop.name = payload.name
        if payload.query_strategy is not None:
            loop.query_strategy = payload.query_strategy
        if payload.model_arch is not None:
            await self._validate_plugin_id(payload.model_arch)
            loop.model_arch = payload.model_arch
        if payload.max_rounds is not None:
            loop.max_rounds = payload.max_rounds
        if payload.query_batch_size is not None:
            loop.query_batch_size = payload.query_batch_size
        if payload.min_seed_labeled is not None:
            loop.min_seed_labeled = payload.min_seed_labeled
        if payload.min_new_labels_per_round is not None:
            loop.min_new_labels_per_round = payload.min_new_labels_per_round
        if payload.stop_patience_rounds is not None:
            loop.stop_patience_rounds = payload.stop_patience_rounds
        if payload.stop_min_gain is not None:
            loop.stop_min_gain = payload.stop_min_gain
        if payload.auto_register_model is not None:
            loop.auto_register_model = payload.auto_register_model

        if payload.global_config is not None:
            loop.global_config = normalize_loop_global_config(payload.global_config)

        if payload.model_request_config is not None:
            loop.global_config = merge_model_request_config(
                loop.global_config,
                payload.model_request_config,
            )

        self.session.add(loop)
        await self.session.flush()
        await self.session.refresh(loop)
        return loop

    async def _known_plugin_ids(self) -> set[str]:
        rows = await self.session.exec(select(RuntimeExecutor))
        plugin_ids: set[str] = set()
        for executor in rows.all():
            for item in extract_executor_plugins(executor.plugin_ids or {}):
                plugin_ids.add(item["plugin_id"])
        return plugin_ids

    async def _validate_plugin_id(self, plugin_id: str) -> None:
        value = str(plugin_id or "").strip()
        if not value:
            raise BadRequestAppException("plugin_id/model_arch is required")
        known_plugin_ids = await self._known_plugin_ids()
        # Backward-compatible: before any executor registers capabilities,
        # keep accepting plugin_id to avoid blocking bootstrap.
        if known_plugin_ids and value not in known_plugin_ids:
            raise BadRequestAppException(f"plugin_id/model_arch not found in runtime catalog: {value}")

    @transactional
    async def assign_executor(self, job_id: uuid.UUID, executor_id: str) -> Job:
        job = await self.repository.get_by_id(job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")
        job.assigned_executor_id = executor_id
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    @transactional
    async def mark_cancelled(self, job_id: uuid.UUID, reason: str | None = None) -> Job:
        job = await self.repository.get_by_id(job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")
        job.status = TrainingJobStatus.CANCELLED
        job.last_error = reason
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def list_loops(self, project_id: uuid.UUID) -> List[ALLoop]:
        return await self.loop_repo.list_by_project(project_id)

    async def list_jobs(self, loop_id: uuid.UUID, limit: int = 50) -> List[Job]:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        stmt = (
            select(Job)
            .where(Job.loop_id == loop_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_events(self, job_id: uuid.UUID, after_seq: int = 0) -> List[JobEvent]:
        await self.repository.get_by_id_or_raise(job_id)
        return await self.job_event_repo.list_by_job_after_seq(job_id, after_seq)

    async def list_metric_series(self, job_id: uuid.UUID, limit: int = 5000) -> List[JobMetricPoint]:
        await self.repository.get_by_id_or_raise(job_id)
        return await self.job_metric_repo.list_by_job(job_id, limit=limit)

    async def list_sampling_candidates(self, job_id: uuid.UUID, limit: int = 200) -> List[JobSampleMetric]:
        stmt = (
            select(JobSampleMetric)
            .where(JobSampleMetric.job_id == job_id)
            .order_by(JobSampleMetric.score.desc())
            .limit(limit)
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_artifacts(self, job_id: uuid.UUID) -> list[dict]:
        job = await self.repository.get_by_id_or_raise(job_id)
        artifacts: list[dict] = []
        for name, value in (job.artifacts or {}).items():
            if not isinstance(value, dict):
                continue
            uri = str(value.get("uri", ""))
            if not self._is_downloadable_uri(uri):
                continue
            artifacts.append(
                {
                    "name": name,
                    "kind": str(value.get("kind", "artifact")),
                    "uri": uri,
                    "meta": value.get("meta") or {},
                }
            )
        return artifacts

    async def get_artifact_download_url(
            self,
            *,
            job_id: uuid.UUID,
            artifact_name: str,
            expires_in_hours: int = 2,
    ) -> str:
        job = await self.repository.get_by_id_or_raise(job_id)
        artifact = (job.artifacts or {}).get(artifact_name)
        if not artifact:
            raise NotFoundAppException(f"Artifact {artifact_name} not found")
        if not isinstance(artifact, dict):
            raise BadRequestAppException("Artifact payload is invalid")

        uri = str(artifact.get("uri") or "")
        if not uri:
            raise BadRequestAppException("Artifact URI is empty")

        if uri.startswith("s3://"):
            _, _, bucket_and_path = uri.partition("s3://")
            _, _, object_path = bucket_and_path.partition("/")
            if not object_path:
                raise BadRequestAppException(f"Invalid S3 URI: {uri}")
            return self.storage.get_presigned_url(
                object_name=object_path,
                expires_delta=timedelta(hours=expires_in_hours),
            )

        if uri.startswith("http://") or uri.startswith("https://"):
            return uri

        raise BadRequestAppException(f"Unsupported artifact URI: {uri}")
