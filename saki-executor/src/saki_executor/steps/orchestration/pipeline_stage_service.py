from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saki_ir import normalize_prediction_candidates
from saki_executor.steps.orchestration.error_codes import TaskErrorCode, TaskStage, wrap_task_error
from saki_executor.steps.orchestration.models import BoundExecutionPlan
from saki_executor.steps.orchestration.training_data_service import TrainingDataService
from saki_plugin_sdk import TaskReporter, TaskRuntimeRequirements, WorkspaceProtocol


@dataclass(frozen=True, slots=True)
class _InferenceTaskProfile:
    name: str
    query_type: str
    candidate_limit_mode: str
    default_strategy: str
    metric_key: str
    skip_when_strategy_empty: bool


class PipelineStageService:
    def __init__(self, *, manager: Any, request: Any) -> None:
        self._manager = manager
        self._request = request

    async def prepare_trained_model_if_needed(
        self,
        *,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> None:
        if not runtime_requirements.requires_trained_model:
            return

        artifact_name = str(runtime_requirements.primary_model_artifact_name or "best.pt").strip() or "best.pt"
        linked = workspace.link_shared_model_to_step(artifact_name)
        if linked is not None and linked.exists():
            bound_plan.effective_plugin_params["model_source"] = "custom_local"
            bound_plan.effective_plugin_params["model_custom_ref"] = str(linked)
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"trained model resolved source=shared artifact={artifact_name} path={linked}"
                    ),
                },
            )
            return

        model_source = str(bound_plan.effective_plugin_params.get("model_source") or "").strip().lower()
        model_ref = str(bound_plan.effective_plugin_params.get("model_custom_ref") or "").strip()
        if model_source in {"custom_url", "custom_local"} and model_ref:
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"trained model resolved source=remote artifact={artifact_name} model_source={model_source}"
                    ),
                },
            )
            return

        message = (
            f"trained model is required but unavailable: "
            f"artifact={artifact_name} task_type={self._request.task_type}"
        )
        if self._manager.strict_train_model_handoff:
            raise wrap_task_error(
                stage=TaskStage.EXECUTE,
                default_code=TaskErrorCode.EXECUTION_FAILED,
                exc=RuntimeError(message),
                message=message,
            )
        await emitter.emit(
            "log",
            {
                "level": "WARN",
                "message": f"{message}; STRICT_TRAIN_MODEL_HANDOFF=false fallback enabled",
            },
        )

    async def execute(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        reporter: TaskReporter,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        try:
            if self._request.task_type in {"score", "predict"}:
                profile = self._inference_profile_for_task(self._request.task_type)
                return await self._run_inference_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    runtime_requirements=runtime_requirements,
                    profile=profile,
                    bound_plan=bound_plan,
                )

            if self._request.task_type == "eval":
                return await self._run_eval_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                    runtime_requirements=runtime_requirements,
                    bound_plan=bound_plan,
                )

            if self._request.task_type == "train":
                return await self._run_train_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                    runtime_requirements=runtime_requirements,
                    bound_plan=bound_plan,
                )

            if self._request.task_type == "custom":
                return await self._run_train_and_sample_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                    runtime_requirements=runtime_requirements,
                    bound_plan=bound_plan,
                )

            raise RuntimeError(f"task_type routing is not implemented: {self._request.task_type}")
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.EXECUTE,
                default_code=TaskErrorCode.EXECUTION_FAILED,
                exc=exc,
                message=f"task execution failed task_id={self._request.task_id}: {exc}",
            ) from exc

    async def _run_training_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[Any, set[str]]:
        protected = await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        output = await plugin.train(
            workspace,
            bound_plan.effective_plugin_params,
            emitter.emit,
            context=bound_plan.execution_context,
        )
        return output, protected

    async def _prepare_plugin_data(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        bound_plan: BoundExecutionPlan,
    ) -> set[str]:
        try:
            runtime_context = bound_plan.plan.runtime_context
            plugin_params_snapshot = {
                key: bound_plan.effective_plugin_params.get(key)
                for key in sorted(bound_plan.effective_plugin_params.keys())
                if not str(key).startswith("_")
            }
            params_snapshot = {
                "global_seed": str(
                    (
                        (
                            self._request.resolved_params.get("reproducibility")
                            if isinstance(self._request.resolved_params.get("reproducibility"), dict)
                            else {}
                        ).get("global_seed")
                        or ""
                    )
                ).strip(),
                "split_seed": runtime_context.split_seed,
                "train_seed": runtime_context.train_seed,
                "sampling_seed": runtime_context.sampling_seed,
                "deterministic_level": str(self._request.resolved_params.get("deterministic_level") or "off"),
                "deterministic": bool(self._request.resolved_params.get("deterministic", False)),
                "strong_deterministic": bool(
                    self._request.resolved_params.get("strong_deterministic", False)
                ),
                "mode": runtime_context.mode,
                "task_type": runtime_context.task_type,
                "round_index": runtime_context.round_index,
                "task_id": runtime_context.task_id,
                "plugin_params": plugin_params_snapshot,
            }
            await emitter.emit("log", {"level": "INFO", "message": f"effective training params: {params_snapshot}"})
            data_service = TrainingDataService(
                fetch_all=self._manager.fetch_all_data,
                cache=self._manager.cache,
                stop_event=self._manager.stop_event,
            )
            data_bundle = await data_service.prepare(
                request=self._request,
                plugin_params=bound_plan.effective_plugin_params,
                runtime_context=runtime_context,
                emit=emitter.emit,
            )
            await plugin.prepare_data(
                workspace=workspace,
                labels=data_bundle.labels,
                samples=data_bundle.samples,
                annotations=data_bundle.train_annotations,
                dataset_ir=data_bundle.ir_batch,
                splits=dict(data_bundle.splits),
                context=bound_plan.execution_context,
            )
            return data_bundle.protected
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.PREPARE_DATA,
                default_code=TaskErrorCode.PREPARE_DATA_FAILED,
                exc=exc,
                message=f"prepare_data failed task_id={self._request.task_id}: {exc}",
            ) from exc

    async def _prepare_data_for_step(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> set[str]:
        if not runtime_requirements.requires_prepare_data:
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"prepare_data skipped by runtime requirements task_type={self._request.task_type}"
                    ),
                },
            )
            return set()

        fingerprint = self._build_data_cache_fingerprint(bound_plan=bound_plan)
        can_use_shared_cache = (
            self._manager.round_shared_cache_enabled
            and self._request.round_id
            and self._request.task_type != "train"
        )
        if can_use_shared_cache:
            try:
                if workspace.restore_shared_data_cache(fingerprint):
                    await emitter.emit(
                        "log",
                        {
                            "level": "INFO",
                            "message": f"round shared data cache hit fingerprint={fingerprint}",
                        },
                    )
                    return set()
            except Exception as exc:
                await emitter.emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": f"round shared data cache restore failed fingerprint={fingerprint} error={exc}",
                    },
                )

        protected = await self._prepare_plugin_data(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            bound_plan=bound_plan,
        )
        if self._manager.round_shared_cache_enabled and self._request.round_id:
            try:
                cached_path = workspace.store_shared_data_cache(
                    fingerprint=fingerprint,
                    source_task_id=self._request.task_id,
                    task_type=self._request.task_type,
                )
                await emitter.emit(
                    "log",
                    {
                        "level": "INFO",
                        "message": f"round shared data cache stored fingerprint={fingerprint} path={cached_path}",
                    },
                )
            except Exception as exc:
                await emitter.emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": f"round shared data cache store failed fingerprint={fingerprint} error={exc}",
                    },
                )
        return protected

    def _build_data_cache_fingerprint(self, *, bound_plan: BoundExecutionPlan) -> str:
        runtime_context = bound_plan.plan.runtime_context
        plugin_subset = {
            key: bound_plan.effective_plugin_params.get(key)
            for key in sorted(bound_plan.effective_plugin_params.keys())
            if not str(key).startswith("_")
        }
        payload = {
            "version": 1,
            "round_id": self._request.round_id,
            "attempt": self._request.attempt,
            "project_id": self._request.project_id,
            "input_commit_id": self._request.input_commit_id,
            "plugin_id": self._request.plugin_id,
            "mode": runtime_context.mode,
            "split_seed": runtime_context.split_seed,
            "plugin_subset": plugin_subset,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _cache_primary_model_after_train(
        self,
        *,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        output_artifacts: list[Any],
    ) -> None:
        if not self._manager.round_shared_cache_enabled or not self._request.round_id:
            return

        artifact_name = str(runtime_requirements.primary_model_artifact_name or "best.pt").strip() or "best.pt"
        primary_artifact = next(
            (item for item in output_artifacts if str(getattr(item, "name", "")).strip() == artifact_name),
            None,
        )
        if primary_artifact is None:
            await emitter.emit(
                "log",
                {
                    "level": "WARN",
                    "message": f"round shared model cache skip: primary artifact not found artifact={artifact_name}",
                },
            )
            return

        source_path = Path(primary_artifact.path)
        if not source_path.exists():
            await emitter.emit(
                "log",
                {
                    "level": "WARN",
                    "message": f"round shared model cache skip: artifact file missing artifact={artifact_name} path={source_path}",
                },
            )
            return

        cached_path = workspace.cache_model_artifact(
            artifact_name=artifact_name,
            source_path=source_path,
            source_task_id=self._request.task_id,
        )
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": f"round shared model cache stored artifact={artifact_name} path={cached_path}",
            },
        )

    async def _run_train_and_sample_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        reporter: TaskReporter,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        output, protected = await self._run_training_pipeline(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        candidates = await self._collect_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
            bound_plan=bound_plan,
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return output.metrics, artifacts, candidates, optional_upload_failures

    async def _run_train_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        reporter: TaskReporter,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        output, _protected = await self._run_training_pipeline(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        await self._cache_primary_model_after_train(
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            output_artifacts=output.artifacts,
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return output.metrics, artifacts, [], optional_upload_failures

    async def _run_eval_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        reporter: TaskReporter,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        output = await plugin.eval(
            workspace,
            bound_plan.effective_plugin_params,
            emitter.emit,
            context=bound_plan.execution_context,
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return output.metrics, artifacts, [], optional_upload_failures

    @staticmethod
    def _inference_profile_for_task(task_type: str) -> _InferenceTaskProfile:
        normalized = str(task_type or "").strip().lower()
        if normalized == "predict":
            return _InferenceTaskProfile(
                name="predict",
                query_type="samples",
                candidate_limit_mode="keep_all",
                default_strategy="uncertainty_1_minus_max_conf",
                metric_key="predict_candidate_count",
                skip_when_strategy_empty=False,
            )
        return _InferenceTaskProfile(
            name="score",
            query_type="unlabeled_samples",
            candidate_limit_mode="review_pool",
            default_strategy="",
            metric_key="score_candidate_count",
            skip_when_strategy_empty=True,
        )

    async def _run_inference_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        profile: _InferenceTaskProfile,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        protected = await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        candidates = await self._collect_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
            profile=profile,
            bound_plan=bound_plan,
        )
        candidates = normalize_prediction_candidates(candidates)
        metrics = {profile.metric_key: float(len(candidates))}
        return metrics, {}, candidates, []

    async def _collect_candidates(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        protected: set[str],
        bound_plan: BoundExecutionPlan,
        profile: _InferenceTaskProfile | None = None,
    ) -> list[dict[str, Any]]:
        mode = self._request.mode
        query_type = "unlabeled_samples"
        candidate_limit_mode = "topk"
        default_strategy = ""
        skip_when_strategy_empty = True
        if profile is not None:
            query_type = profile.query_type
            candidate_limit_mode = profile.candidate_limit_mode
            default_strategy = profile.default_strategy
            skip_when_strategy_empty = profile.skip_when_strategy_empty

        is_keep_all = candidate_limit_mode == "keep_all"
        skip_sampling = bool(self._request.resolved_params.get("skip_sampling", False))
        if mode == "manual" and not is_keep_all:
            await emitter.emit("log", {"level": "INFO", "message": "manual mode: skip sampling"})
            return []
        if skip_sampling:
            await emitter.emit("log", {"level": "INFO", "message": "skip_sampling=true, TopK sampling skipped"})
            return []

        sampling_cfg = self._request.resolved_params.get("sampling")
        sampling_cfg = dict(sampling_cfg) if isinstance(sampling_cfg, dict) else {}
        strategy = str(
            sampling_cfg.get("strategy")
            or self._request.query_strategy
            or default_strategy
        ).strip()
        if not strategy:
            if skip_when_strategy_empty:
                await emitter.emit("log", {"level": "INFO", "message": "sampling strategy is empty, skip sampling"})
                return []
            strategy = "uncertainty_1_minus_max_conf"
        topk = int(sampling_cfg.get("topk", self._request.resolved_params.get("topk", 200)))
        review_pool_size = int(sampling_cfg.get("review_pool_size", 0) or 0)
        if review_pool_size <= 0:
            review_pool_multiplier = int(sampling_cfg.get("review_pool_multiplier", 3) or 3)
            review_pool_multiplier = max(1, review_pool_multiplier)
            review_pool_size = max(topk, topk * review_pool_multiplier)
        if candidate_limit_mode == "keep_all":
            candidate_limit = 0
        elif candidate_limit_mode == "review_pool":
            candidate_limit = max(topk, review_pool_size)
        else:
            candidate_limit = topk
        sampling_params = dict(bound_plan.effective_plugin_params)
        sampling_params.update(sampling_cfg)
        sampling_params["sampling_topk"] = candidate_limit
        runtime_context = bound_plan.plan.runtime_context
        sampling_params["sampling_seed"] = int(
            sampling_params.get("sampling_seed", runtime_context.sampling_seed)
        )
        return await self._manager.collect_topk_candidates_streaming(
            plugin=plugin,
            workspace=workspace,
            task_id=self._request.task_id,
            project_id=self._request.project_id,
            commit_id=self._request.input_commit_id,
            strategy=strategy,
            params=sampling_params,
            protected=protected,
            query_type=query_type,
            topk=candidate_limit,
            context=bound_plan.execution_context,
        )

    async def _upload_artifacts(
        self,
        *,
        output_artifacts: list[Any],
        reporter: TaskReporter,
    ) -> tuple[dict[str, Any], list[str]]:
        artifacts: dict[str, Any] = {}
        optional_upload_failures: list[str] = []
        for artifact in output_artifacts:
            artifact_path = Path(artifact.path)
            required = bool(getattr(artifact, "required", False))
            try:
                ticket = await self._manager.request_upload_ticket(
                    task_id=self._request.task_id,
                    artifact_name=artifact.name,
                    content_type=artifact.content_type,
                )
                upload_url = ticket.upload_url
                storage_uri = ticket.storage_uri
                headers = dict(ticket.headers)
                size = artifact_path.stat().st_size
                await self._manager.upload_artifact_with_retry(
                    artifact_path=artifact_path,
                    upload_url=upload_url,
                    headers=headers,
                )
            except Exception as exc:
                message = f"artifact={artifact.name} required={required} error={exc}"
                if required:
                    raise wrap_task_error(
                        stage=TaskStage.FINALIZE,
                        default_code=TaskErrorCode.ARTIFACT_UPLOAD_FAILED,
                        exc=exc,
                        message=f"required artifact upload failed: {message}",
                    ) from exc
                optional_upload_failures.append(message)
                continue

            artifacts[artifact.name] = {
                "kind": artifact.kind,
                "uri": storage_uri,
                "meta": artifact.meta or {"size": size},
            }
            await self._manager.push_task_event(
                self._request.task_id,
                reporter.artifact(
                    kind=artifact.kind,
                    name=artifact.name,
                    uri=storage_uri,
                    meta=artifact.meta or {"size": size},
                ),
            )

        return artifacts, optional_upload_failures
