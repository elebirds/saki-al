"""Job Service - business logic for Loop/Job/Task runtime."""

from __future__ import annotations

import math
import re
import uuid
from datetime import timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.db.transaction import transactional
from saki_api.models.enums import (
    ALLoopMode,
    ALLoopStatus,
    JobStatusV2,
    JobTaskStatus,
    JobTaskType,
    LoopPhase,
)
from saki_api.models.project.branch import Branch
from saki_api.models.runtime.job import Job
from saki_api.models.runtime.job_task import JobTask
from saki_api.models.runtime.loop import ALLoop
from saki_api.models.runtime.runtime_executor import RuntimeExecutor
from saki_api.models.runtime.task_candidate_item import TaskCandidateItem
from saki_api.repositories.runtime.job import JobRepository
from saki_api.repositories.runtime.job_task import JobTaskRepository
from saki_api.repositories.runtime.loop import LoopRepository
from saki_api.repositories.runtime.task_candidate_item import TaskCandidateItemRepository
from saki_api.repositories.runtime.task_event import TaskEventRepository
from saki_api.repositories.runtime.task_metric_point import TaskMetricPointRepository
from saki_api.schemas.runtime.job import (
    JobCreateRequest,
    LoopCreateRequest,
    LoopSimulationConfig,
    LoopUpdateRequest,
    SimulationExperimentCreateRequest,
)
from saki_api.services.base import BaseService
from saki_api.services.runtime.loop_config import (
    extract_model_request_config,
    merge_model_request_config,
    normalize_loop_global_config,
)
from saki_api.services.runtime.runtime_plugin_catalog import extract_executor_plugins
from saki_api.services.system.system_settings_reader import system_settings_reader
from saki_api.utils.storage import get_storage_provider


class JobService(BaseService[Job, JobRepository, JobCreateRequest, JobCreateRequest]):
    RANDOM_BASELINE_STRATEGY = "random_baseline"

    def __init__(self, session: AsyncSession):
        super().__init__(Job, JobRepository, session)
        self.session = session
        self.loop_repo = LoopRepository(session)
        self.job_task_repo = JobTaskRepository(session)
        self.task_event_repo = TaskEventRepository(session)
        self.task_metric_repo = TaskMetricPointRepository(session)
        self.task_candidate_repo = TaskCandidateItemRepository(session)
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    @staticmethod
    def _is_downloadable_uri(uri: str | None) -> bool:
        raw = str(uri or "").strip()
        return raw.startswith("s3://") or raw.startswith("http://") or raw.startswith("https://")

    @staticmethod
    def _normalize_branch_segment(raw: str, *, fallback: str) -> str:
        value = re.sub(r"[^0-9A-Za-z._-]+", "-", str(raw or "").strip().lower())
        value = value.strip("._-")
        return value or fallback

    @staticmethod
    def _truncate(raw: str, *, max_len: int = 100) -> str:
        value = str(raw or "").strip()
        if len(value) <= max_len:
            return value
        return value[:max_len].rstrip("._-/") or value[:max_len]

    @staticmethod
    def _phase_for_mode(mode: ALLoopMode) -> LoopPhase:
        if mode == ALLoopMode.SIMULATION:
            return LoopPhase.SIM_BOOTSTRAP
        if mode == ALLoopMode.MANUAL:
            return LoopPhase.MANUAL_IDLE
        return LoopPhase.AL_BOOTSTRAP

    @staticmethod
    def _normalize_simulation_config(raw: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw or {})
        oracle_commit_id = str(payload.get("oracle_commit_id") or "").strip()
        if oracle_commit_id:
            try:
                oracle_commit_id = str(uuid.UUID(oracle_commit_id))
            except Exception as exc:
                raise BadRequestAppException("invalid simulation oracle_commit_id") from exc

        seed_ratio = float(payload.get("seed_ratio", 0.05) or 0.05)
        step_ratio = float(payload.get("step_ratio", 0.05) or 0.05)
        max_rounds = max(1, int(payload.get("max_rounds", 20) or 20))
        seeds_raw = payload.get("seeds") or [0, 1, 2, 3, 4]
        seeds: list[int] = []
        for item in seeds_raw:
            try:
                seeds.append(int(item))
            except Exception:
                continue
        if not seeds:
            seeds = [0, 1, 2, 3, 4]

        return {
            "oracle_commit_id": oracle_commit_id,
            "seed_ratio": min(1.0, max(0.0, seed_ratio)),
            "step_ratio": min(1.0, max(0.0, step_ratio)),
            "max_rounds": max_rounds,
            "random_baseline_enabled": bool(payload.get("random_baseline_enabled", True)),
            "seeds": seeds,
        }

    @staticmethod
    def _extract_simulation_config(global_config: dict[str, Any]) -> dict[str, Any]:
        payload = global_config.get("simulation")
        if not isinstance(payload, dict):
            return JobService._normalize_simulation_config({})
        return JobService._normalize_simulation_config(payload)

    async def _get_system_simulation_defaults(self) -> dict[str, Any]:
        return await system_settings_reader.get_simulation_defaults()

    async def _resolve_simulation_config(
        self,
        *,
        simulation_config: LoopSimulationConfig,
        include_fields: set[str] | None = None,
    ) -> dict[str, Any]:
        defaults = await self._get_system_simulation_defaults()
        include = include_fields if include_fields is not None else None
        payload = simulation_config.model_dump(
            exclude_none=True,
            include=include,
        )
        return self._normalize_simulation_config({**defaults, **payload})

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
        known = await self._known_plugin_ids()
        if known and value not in known:
            raise BadRequestAppException(f"plugin_id/model_arch not found in runtime catalog: {value}")

    async def _next_available_branch_name(self, *, project_id: uuid.UUID, base_name: str) -> str:
        candidate = self._truncate(base_name, max_len=100)
        suffix = 1
        while True:
            stmt = select(Branch.id).where(Branch.project_id == project_id, Branch.name == candidate)
            if not (await self.session.exec(stmt)).first():
                return candidate
            suffix_token = f"-{suffix}"
            prefix_len = max(1, 100 - len(suffix_token))
            candidate_prefix = self._truncate(base_name, max_len=prefix_len)
            candidate = f"{candidate_prefix}{suffix_token}"
            suffix += 1

    @transactional
    async def create_loop(self, project_id: uuid.UUID, payload: LoopCreateRequest) -> ALLoop:
        branch = await self.session.get(Branch, payload.branch_id)
        if not branch:
            raise NotFoundAppException(f"Branch {payload.branch_id} not found")
        if branch.project_id != project_id:
            raise BadRequestAppException("Branch does not belong to this project")

        await self._validate_plugin_id(payload.model_arch)

        existing = await self.loop_repo.get_one(filters=[ALLoop.branch_id == payload.branch_id])
        if existing:
            raise BadRequestAppException("Branch already has a loop bound")

        normalized_global_config = normalize_loop_global_config(payload.global_config)
        normalized_global_config = merge_model_request_config(normalized_global_config, payload.model_request_config)
        normalized_global_config["simulation"] = await self._resolve_simulation_config(
            simulation_config=payload.simulation_config,
            include_fields=set(payload.simulation_config.model_fields_set)
            if "simulation_config" in payload.model_fields_set
            else set(),
        )

        if payload.mode == ALLoopMode.SIMULATION:
            simulation_config = self._extract_simulation_config(normalized_global_config)
            if not simulation_config.get("oracle_commit_id"):
                raise BadRequestAppException("simulation mode requires oracle_commit_id")

        loop = ALLoop(
            project_id=project_id,
            branch_id=payload.branch_id,
            name=payload.name,
            mode=payload.mode,
            phase=self._phase_for_mode(payload.mode),
            phase_meta={},
            query_strategy=payload.query_strategy,
            model_arch=payload.model_arch,
            experiment_group_id=payload.experiment_group_id,
            global_config=normalized_global_config,
            current_iteration=0,
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
        if payload.mode is not None:
            loop.mode = payload.mode
            loop.phase = self._phase_for_mode(payload.mode)
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
            loop.global_config = merge_model_request_config(loop.global_config, payload.model_request_config)

        if payload.simulation_config is not None:
            loop.global_config = dict(loop.global_config or {})
            loop.global_config["simulation"] = await self._resolve_simulation_config(
                simulation_config=payload.simulation_config,
                include_fields=set(payload.simulation_config.model_fields_set),
            )

        if loop.mode == ALLoopMode.SIMULATION:
            simulation_config = self._extract_simulation_config(loop.global_config)
            if not simulation_config.get("oracle_commit_id"):
                raise BadRequestAppException("simulation mode requires oracle_commit_id")

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

        group_id = uuid.uuid4()
        simulation_config = await self._resolve_simulation_config(
            simulation_config=payload.simulation_config,
            include_fields=set(payload.simulation_config.model_fields_set),
        )

        strategies: list[str] = []
        for raw in payload.strategies:
            key = str(raw or "").strip()
            if not key or key in strategies:
                continue
            strategies.append(key)
        if self.RANDOM_BASELINE_STRATEGY not in strategies:
            strategies.insert(0, self.RANDOM_BASELINE_STRATEGY)
        if not strategies:
            raise BadRequestAppException("strategies must contain at least one item")

        experiment_name = str(payload.experiment_name or f"sim-{str(group_id)[:8]}").strip()
        group_token = str(group_id).split("-")[0]

        loops: list[ALLoop] = []
        for strategy in strategies:
            for seed in simulation_config["seeds"]:
                strategy_segment = self._normalize_branch_segment(strategy, fallback="strategy")
                branch_name = await self._next_available_branch_name(
                    project_id=project_id,
                    base_name=f"simulation/{group_token}/{strategy_segment}/seed-{seed}",
                )
                fork_branch = Branch(
                    project_id=project_id,
                    name=branch_name,
                    head_commit_id=branch.head_commit_id,
                    description=self._truncate(f"[simulation] {experiment_name} · {strategy} · seed={seed}", max_len=500),
                    is_protected=False,
                )
                self.session.add(fork_branch)
                await self.session.flush()
                await self.session.refresh(fork_branch)

                loop_global_config = dict(payload.global_config or {})
                loop_global_config["simulation"] = {
                    **simulation_config,
                    "single_seed": seed,
                }
                loop_payload = LoopCreateRequest(
                    name=self._truncate(f"{experiment_name}-{strategy}-seed-{seed}", max_len=100),
                    branch_id=fork_branch.id,
                    mode=ALLoopMode.SIMULATION,
                    query_strategy=strategy,
                    model_arch=payload.model_arch,
                    global_config=loop_global_config,
                    model_request_config=payload.model_request_config,
                    simulation_config=payload.simulation_config,
                    experiment_group_id=group_id,
                    status=payload.status,
                    max_rounds=simulation_config["max_rounds"],
                    query_batch_size=max(1, int(math.ceil(simulation_config["step_ratio"] * 1000))),
                )
                loop = await self.create_loop(project_id=project_id, payload=loop_payload)
                loops.append(loop)

        return group_id, loops

    @transactional
    async def create_job_for_loop(self, loop_id: uuid.UUID, payload: JobCreateRequest) -> Job:
        loop = await self.loop_repo.get_by_id(loop_id)
        if not loop:
            raise NotFoundAppException(f"Loop {loop_id} not found")
        if loop.project_id != payload.project_id:
            raise BadRequestAppException("Loop project_id and request.project_id mismatch")

        loop.current_iteration += 1
        self.session.add(loop)

        job = Job(
            project_id=payload.project_id,
            loop_id=loop_id,
            round_index=loop.current_iteration,
            mode=payload.mode,
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            source_commit_id=payload.source_commit_id,
            job_type=payload.job_type,
            plugin_id=payload.plugin_id,
            query_strategy=payload.query_strategy,
            params=payload.params,
            resources=payload.resources,
            strategy_params=payload.strategy_params,
            final_metrics={},
            final_artifacts={},
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def list_loops(self, project_id: uuid.UUID) -> List[ALLoop]:
        return await self.loop_repo.list_by_project(project_id)

    async def list_jobs(self, loop_id: uuid.UUID, limit: int = 50) -> List[Job]:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        stmt = select(Job).where(Job.loop_id == loop_id).order_by(Job.round_index.desc()).limit(limit)
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_tasks(self, job_id: uuid.UUID, limit: int = 1000) -> List[JobTask]:
        await self.repository.get_by_id_or_raise(job_id)
        stmt = (
            select(JobTask)
            .where(JobTask.job_id == job_id)
            .order_by(JobTask.task_index.asc(), JobTask.created_at.asc())
            .limit(max(1, min(limit, 5000)))
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_task_events(self, task_id: uuid.UUID, after_seq: int = 0, limit: int = 5000):
        await self.job_task_repo.get_by_id_or_raise(task_id)
        return await self.task_event_repo.list_by_task_after_seq(
            task_id=task_id,
            after_seq=max(0, after_seq),
            limit=max(1, min(limit, 100000)),
        )

    async def list_task_metric_series(self, task_id: uuid.UUID, limit: int = 5000):
        await self.job_task_repo.get_by_id_or_raise(task_id)
        return await self.task_metric_repo.list_by_task(task_id, limit=max(1, min(limit, 100000)))

    async def list_task_candidates(self, task_id: uuid.UUID, limit: int = 200) -> List[TaskCandidateItem]:
        await self.job_task_repo.get_by_id_or_raise(task_id)
        return await self.task_candidate_repo.list_topk_by_task(task_id, limit=max(1, min(limit, 5000)))

    async def list_task_artifacts(self, task_id: uuid.UUID) -> list[dict]:
        task = await self.job_task_repo.get_by_id_or_raise(task_id)
        artifacts: list[dict] = []
        for name, value in (task.artifacts or {}).items():
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

    async def get_task_artifact_download_url(
        self,
        *,
        task_id: uuid.UUID,
        artifact_name: str,
        expires_in_hours: int = 2,
    ) -> str:
        task = await self.job_task_repo.get_by_id_or_raise(task_id)
        artifact = (task.artifacts or {}).get(artifact_name)
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

    @transactional
    async def mark_job_cancelled(self, job_id: uuid.UUID, reason: str | None = None) -> Job:
        job = await self.repository.get_by_id(job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")

        job.summary_status = JobStatusV2.JOB_CANCELLED
        job.last_error = reason
        self.session.add(job)

        stmt = select(JobTask).where(
            JobTask.job_id == job_id,
            JobTask.status.in_(
                [
                    JobTaskStatus.PENDING,
                    JobTaskStatus.DISPATCHING,
                    JobTaskStatus.RUNNING,
                    JobTaskStatus.RETRYING,
                ]
            ),
        )
        rows = await self.session.exec(stmt)
        tasks = list(rows.all())
        for task in tasks:
            task.status = JobTaskStatus.CANCELLED
            task.last_error = reason
            self.session.add(task)

        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def summarize_loop(self, loop_id: uuid.UUID) -> dict[str, Any]:
        await self.loop_repo.get_by_id_or_raise(loop_id)

        jobs = list((await self.session.exec(select(Job).where(Job.loop_id == loop_id))).all())
        if not jobs:
            return {
                "jobs_total": 0,
                "jobs_succeeded": 0,
                "tasks_total": 0,
                "tasks_succeeded": 0,
                "metrics_latest": {},
            }

        job_ids = [job.id for job in jobs]
        tasks = list((await self.session.exec(select(JobTask).where(JobTask.job_id.in_(job_ids)))).all())
        latest_job = sorted(jobs, key=lambda item: (item.round_index, item.created_at))[-1]

        return {
            "jobs_total": len(jobs),
            "jobs_succeeded": sum(1 for item in jobs if item.summary_status == JobStatusV2.JOB_SUCCEEDED),
            "tasks_total": len(tasks),
            "tasks_succeeded": sum(1 for item in tasks if item.status == JobTaskStatus.SUCCEEDED),
            "metrics_latest": dict(latest_job.final_metrics or {}),
        }

    async def get_simulation_experiment_comparison(
        self,
        *,
        experiment_group_id: uuid.UUID,
        metric_name: str = "map50",
    ) -> dict[str, Any]:
        loops = list(
            (
                await self.session.exec(
                    select(ALLoop)
                    .where(ALLoop.experiment_group_id == experiment_group_id)
                    .order_by(ALLoop.created_at.asc())
                )
            ).all()
        )
        if not loops:
            raise NotFoundAppException(f"Simulation experiment {experiment_group_id} not found")

        by_strategy: dict[str, dict[int, list[tuple[int, float]]]] = {}
        summary_rows: dict[str, list[tuple[int, float]]] = {}

        for loop in loops:
            simulation_config = self._extract_simulation_config(loop.global_config or {})
            single_seed = int((loop.global_config or {}).get("simulation", {}).get("single_seed", 0))
            strategy = str(loop.query_strategy or "")
            strategy_data = by_strategy.setdefault(strategy, {})

            jobs = list(
                (
                    await self.session.exec(
                        select(Job)
                        .where(Job.loop_id == loop.id)
                        .order_by(Job.round_index.asc())
                    )
                ).all()
            )
            final_metrics = []
            for job in jobs:
                m = float((job.final_metrics or {}).get(metric_name) or 0.0)
                final_metrics.append((job.round_index, m))
                strategy_data.setdefault(job.round_index, []).append((single_seed, m))

            if final_metrics:
                aulc = mean([row[1] for row in final_metrics])
                summary_rows.setdefault(strategy, []).append((single_seed, aulc))

        curves: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []

        baseline = self.RANDOM_BASELINE_STRATEGY if self.RANDOM_BASELINE_STRATEGY in by_strategy else list(by_strategy)[0]

        baseline_final_mean = 0.0
        if baseline in by_strategy:
            baseline_rounds = sorted(by_strategy[baseline].items(), key=lambda item: item[0])
            if baseline_rounds:
                baseline_last_values = [row[1] for _, rows in baseline_rounds for row in rows]
                baseline_final_mean = mean(baseline_last_values) if baseline_last_values else 0.0

        delta_vs_baseline: dict[str, float] = {}

        for strategy, round_map in sorted(by_strategy.items(), key=lambda item: item[0]):
            rounds_sorted = sorted(round_map.items(), key=lambda item: item[0])
            for round_index, items in rounds_sorted:
                values = [row[1] for row in items]
                curves.append(
                    {
                        "strategy": strategy,
                        "round_index": int(round_index),
                        "target_ratio": round(
                            min(1.0, self._extract_simulation_config(loops[0].global_config).get("seed_ratio", 0.05)
                                + round_index * self._extract_simulation_config(loops[0].global_config).get("step_ratio", 0.05)),
                            6,
                        ),
                        "mean_metric": float(mean(values) if values else 0.0),
                        "std_metric": float(pstdev(values) if len(values) > 1 else 0.0),
                    }
                )

            final_values = [items[-1][1] for _, items in rounds_sorted if items]
            aulc_values = [row[1] for row in summary_rows.get(strategy, [])]
            final_mean = float(mean(final_values) if final_values else 0.0)
            summaries.append(
                {
                    "strategy": strategy,
                    "seeds": [seed for seed, _ in summary_rows.get(strategy, [])],
                    "final_mean": final_mean,
                    "final_std": float(pstdev(final_values) if len(final_values) > 1 else 0.0),
                    "aulc_mean": float(mean(aulc_values) if aulc_values else 0.0),
                }
            )
            delta_vs_baseline[strategy] = final_mean - baseline_final_mean

        return {
            "experiment_group_id": experiment_group_id,
            "metric_name": metric_name,
            "curves": curves,
            "strategies": summaries,
            "baseline_strategy": baseline,
            "delta_vs_baseline": delta_vs_baseline,
        }

    @transactional
    async def confirm_loop_step(self, loop_id: uuid.UUID) -> ALLoop:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        if loop.mode != ALLoopMode.MANUAL:
            raise BadRequestAppException("confirm is only available in manual mode")
        if loop.phase != LoopPhase.MANUAL_WAIT_CONFIRM:
            raise BadRequestAppException("loop is not waiting for manual confirmation")

        loop.phase = LoopPhase.MANUAL_FINALIZE
        self.session.add(loop)
        await self.session.flush()
        await self.session.refresh(loop)
        return loop

    async def get_task_by_id_or_raise(self, task_id: uuid.UUID) -> JobTask:
        return await self.job_task_repo.get_by_id_or_raise(task_id)

    @transactional
    async def mark_task_cancelled(self, task_id: uuid.UUID, reason: str | None = None) -> JobTask:
        task = await self.job_task_repo.get_by_id(task_id)
        if not task:
            raise NotFoundAppException(f"Task {task_id} not found")
        if task.status in {
            JobTaskStatus.SUCCEEDED,
            JobTaskStatus.FAILED,
            JobTaskStatus.CANCELLED,
            JobTaskStatus.SKIPPED,
        }:
            return task

        task.status = JobTaskStatus.CANCELLED
        task.last_error = reason
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task
