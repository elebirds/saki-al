"""
Job Service - Business logic for L3 runtime jobs.
"""

import re
import uuid
from datetime import timedelta
from typing import Any, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.db.transaction import transactional
from saki_api.models.enums import TrainingJobStatus, ALLoopMode
from saki_api.models.l2.branch import Branch
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_event import JobEvent
from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.models.l3.loop import ALLoop
from saki_api.models.l3.loop_round import LoopRound
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.repositories.job import JobRepository
from saki_api.repositories.job_event import JobEventRepository
from saki_api.repositories.job_metric_point import JobMetricPointRepository
from saki_api.repositories.loop import LoopRepository
from saki_api.schemas.l3.job import (
    JobCreateRequest,
    LoopCreateRequest,
    LoopUpdateRequest,
    SimulationExperimentCreateRequest,
)
from saki_api.services.loop_config import (
    extract_simulation_config,
    normalize_loop_global_config,
    merge_model_request_config,
    merge_simulation_config,
)
from saki_api.services.runtime_plugin_catalog import extract_executor_plugins
from saki_api.services.base import BaseService
from saki_api.utils.storage import get_storage_provider


class JobService(BaseService[Job, JobRepository, JobCreateRequest, JobCreateRequest]):
    """Service for runtime Job lifecycle and read APIs."""
    RANDOM_BASELINE_STRATEGY = "random_baseline"

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

    @staticmethod
    def _normalize_experiment_name(
            *,
            experiment_name: str | None,
            group_id: uuid.UUID,
    ) -> str:
        raw = str(experiment_name or "").strip()
        if raw:
            return raw
        return f"simulation-exp-{str(group_id).split('-')[0]}"

    @staticmethod
    def _normalize_branch_segment(raw: str, *, fallback: str) -> str:
        value = re.sub(r"[^0-9A-Za-z._-]+", "-", str(raw or "").strip().lower())
        value = value.strip("._-")
        return value or fallback

    @staticmethod
    def _truncate_with_suffix(raw: str, *, max_len: int = 100) -> str:
        value = str(raw or "").strip()
        if len(value) <= max_len:
            return value
        return value[:max_len].rstrip("._-/") or value[:max_len]

    async def _next_available_branch_name(self, *, project_id: uuid.UUID, base_name: str) -> str:
        candidate = self._truncate_with_suffix(base_name, max_len=100)
        if not candidate:
            candidate = "simulation/experiment"
        suffix = 1
        while True:
            stmt = select(Branch.id).where(
                Branch.project_id == project_id,
                Branch.name == candidate,
            )
            exists = (await self.session.exec(stmt)).first()
            if not exists:
                return candidate
            suffix_token = f"-{suffix}"
            prefix_len = max(1, 100 - len(suffix_token))
            candidate_prefix = self._truncate_with_suffix(base_name, max_len=prefix_len)
            candidate = f"{candidate_prefix}{suffix_token}"
            suffix += 1

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
        if payload.mode == ALLoopMode.SIMULATION and payload.simulation_config.oracle_commit_id is None:
            raise BadRequestAppException("simulation_config.oracle_commit_id is required when mode=simulation")

        normalized_global_config = normalize_loop_global_config(payload.global_config)
        normalized_global_config = merge_model_request_config(
            normalized_global_config,
            payload.model_request_config,
        )
        normalized_global_config = merge_simulation_config(
            normalized_global_config,
            payload.simulation_config.model_dump(exclude_none=True) if payload.simulation_config else None,
        )

        query_batch_size = payload.query_batch_size
        max_rounds = payload.max_rounds
        if payload.mode == ALLoopMode.SIMULATION:
            query_batch_size = payload.simulation_config.query_batch_size
            max_rounds = payload.simulation_config.max_rounds

        loop = ALLoop(
            project_id=project_id,
            branch_id=payload.branch_id,
            name=payload.name,
            mode=payload.mode,
            query_strategy=payload.query_strategy,
            model_arch=payload.model_arch,
            experiment_group_id=payload.experiment_group_id,
            global_config=normalized_global_config,
            current_iteration=0,
            status=payload.status,
            max_rounds=max_rounds,
            query_batch_size=query_batch_size,
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
        if payload.mode is not None:
            loop.mode = payload.mode
        if payload.query_strategy is not None:
            loop.query_strategy = payload.query_strategy
        if payload.model_arch is not None:
            await self._validate_plugin_id(payload.model_arch)
            loop.model_arch = payload.model_arch
        if payload.experiment_group_id is not None:
            loop.experiment_group_id = payload.experiment_group_id
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

        if payload.simulation_config is not None:
            loop.global_config = merge_simulation_config(
                loop.global_config,
                payload.simulation_config.model_dump(exclude_none=True),
            )
            if loop.mode == ALLoopMode.SIMULATION:
                loop.query_batch_size = payload.simulation_config.query_batch_size
                loop.max_rounds = payload.simulation_config.max_rounds

        mode_value = loop.mode if isinstance(loop.mode, ALLoopMode) else ALLoopMode(
            str(getattr(loop.mode, "value", loop.mode) or ALLoopMode.ACTIVE_LEARNING.value)
        )
        if mode_value == ALLoopMode.SIMULATION:
            simulation_config = extract_simulation_config(loop.global_config)
            if not simulation_config.get("oracle_commit_id"):
                raise BadRequestAppException("simulation_config.oracle_commit_id is required when mode=simulation")

        self.session.add(loop)
        await self.session.flush()
        await self.session.refresh(loop)
        return loop

    @transactional
    async def create_simulation_experiment(
            self,
            *,
            project_id: uuid.UUID,
            payload: SimulationExperimentCreateRequest,
    ) -> tuple[uuid.UUID, List[ALLoop]]:
        branch = await self.session.get(Branch, payload.branch_id)
        if not branch:
            raise NotFoundAppException(f"Branch {payload.branch_id} not found")
        if branch.project_id != project_id:
            raise BadRequestAppException("Branch does not belong to this project")
        await self._validate_plugin_id(payload.model_arch)
        if payload.model_arch == "demo_det_v1":
            raise BadRequestAppException("demo_det_v1 is demo-only and not allowed for simulation experiments")

        strategy_values: list[str] = []
        for raw in payload.strategies:
            key = str(raw or "").strip()
            if not key:
                continue
            if key in strategy_values:
                continue
            strategy_values.append(key)
        if self.RANDOM_BASELINE_STRATEGY not in strategy_values:
            strategy_values.insert(0, self.RANDOM_BASELINE_STRATEGY)
        if not strategy_values:
            raise BadRequestAppException("strategies must contain at least one item")

        group_id = uuid.uuid4()
        experiment_name = self._normalize_experiment_name(
            experiment_name=payload.experiment_name,
            group_id=group_id,
        )
        group_token = str(group_id).split("-")[0]
        experiment_segment = self._normalize_branch_segment(experiment_name, fallback="simulation-exp")
        branch_prefix = f"simulation/{experiment_segment}/{group_token}"
        loops: list[ALLoop] = []
        for index, strategy in enumerate(strategy_values, start=1):
            strategy_segment = self._normalize_branch_segment(strategy, fallback=f"strategy-{index}")
            branch_name = await self._next_available_branch_name(
                project_id=project_id,
                base_name=f"{branch_prefix}/{strategy_segment}",
            )
            fork_branch = Branch(
                project_id=project_id,
                name=branch_name,
                head_commit_id=branch.head_commit_id,
                description=self._truncate_with_suffix(
                    f"[simulation] {experiment_name} · {strategy}",
                    max_len=500,
                ),
                is_protected=False,
            )
            self.session.add(fork_branch)
            await self.session.flush()
            await self.session.refresh(fork_branch)

            loop_payload = LoopCreateRequest(
                name=self._truncate_with_suffix(f"{experiment_name}-{index}-{strategy}", max_len=100),
                branch_id=fork_branch.id,
                mode=ALLoopMode.SIMULATION,
                query_strategy=strategy,
                model_arch=payload.model_arch,
                global_config=payload.global_config,
                model_request_config=payload.model_request_config,
                simulation_config=payload.simulation_config,
                experiment_group_id=group_id,
                status=payload.status,
            )
            loop = await self.create_loop(project_id=project_id, payload=loop_payload)
            loops.append(loop)
        return group_id, loops

    async def get_simulation_experiment_curves(self, *, experiment_group_id: uuid.UUID) -> dict[str, Any]:
        rows = await self.session.exec(
            select(ALLoop)
            .where(ALLoop.experiment_group_id == experiment_group_id)
            .order_by(ALLoop.created_at.asc())
        )
        loops = list(rows.all())
        if not loops:
            raise NotFoundAppException(f"Simulation experiment {experiment_group_id} not found")

        payload_loops: list[dict[str, Any]] = []
        for loop in loops:
            rounds = await self.list_rounds(loop.id, limit=2000, ensure_loop_exists=False)
            points: list[dict[str, Any]] = []
            for item in rounds:
                metrics = dict(item.metrics or {})
                points.append(
                    {
                        "round_index": int(item.round_index),
                        "labeled_count": int(item.labeled_count or 0),
                        "map50": float(metrics.get("map50") or 0.0),
                        "recall": float(metrics.get("recall") or 0.0),
                    }
                )
            payload_loops.append(
                {
                    "loop_id": loop.id,
                    "loop_name": loop.name,
                    "query_strategy": loop.query_strategy,
                    "points": points,
                }
            )

        return {
            "experiment_group_id": experiment_group_id,
            "loops": payload_loops,
        }

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

    async def list_rounds(
            self,
            loop_id: uuid.UUID,
            *,
            limit: int = 200,
            ensure_loop_exists: bool = True,
    ) -> List[LoopRound]:
        if ensure_loop_exists:
            await self.loop_repo.get_by_id_or_raise(loop_id)
        safe_limit = max(1, min(int(limit), 2000))
        stmt = (
            select(LoopRound)
            .where(LoopRound.loop_id == loop_id)
            .order_by(LoopRound.round_index.asc())
            .limit(safe_limit)
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def summarize_loop(
            self,
            loop_id: uuid.UUID,
            *,
            ensure_loop_exists: bool = True,
    ) -> dict[str, Any]:
        if ensure_loop_exists:
            await self.loop_repo.get_by_id_or_raise(loop_id)

        stmt = select(LoopRound).where(LoopRound.loop_id == loop_id).order_by(LoopRound.round_index.asc())
        result = await self.session.exec(stmt)
        rounds = list(result.all())

        rounds_completed = [
            item
            for item in rounds
            if str(getattr(item.status, "value", item.status)) in {"completed", "completed_no_candidates"}
        ]
        metrics_latest = rounds_completed[-1].metrics if rounds_completed else {}
        return {
            "rounds_total": len(rounds),
            "rounds_completed": len(rounds_completed),
            "selected_total": sum(int(item.selected_count or 0) for item in rounds),
            "labeled_total": sum(int(item.labeled_count or 0) for item in rounds),
            "metrics_latest": metrics_latest or {},
        }

    async def list_events_chunk(
            self,
            job_id: uuid.UUID,
            *,
            after_seq: int = 0,
            limit: int = 5000,
            ensure_job_exists: bool = True,
    ) -> List[JobEvent]:
        if ensure_job_exists:
            await self.repository.get_by_id_or_raise(job_id)
        safe_after_seq = max(0, int(after_seq))
        safe_limit = max(1, min(int(limit), 100000))
        return await self.job_event_repo.list_by_job_after_seq(
            job_id=job_id,
            after_seq=safe_after_seq,
            limit=safe_limit,
        )

    async def list_events(self, job_id: uuid.UUID, after_seq: int = 0) -> List[JobEvent]:
        return await self.list_events_chunk(
            job_id=job_id,
            after_seq=after_seq,
            limit=5000,
            ensure_job_exists=True,
        )

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
