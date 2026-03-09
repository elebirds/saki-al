from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from saki_ir import normalize_prediction_candidates
from saki_executor.steps.contracts import TaskExecutionRequest
from saki_executor.steps.orchestration.error_codes import TaskErrorCode, TaskStage, wrap_task_error
from saki_executor.steps.orchestration.models import BoundExecutionPlan
from saki_executor.steps.orchestration.training_data_service import TrainingDataService
from saki_plugin_sdk import TaskReporter, TaskRuntimeRequirements, WorkspaceProtocol


class PipelineStageService:
    def __init__(self, *, manager: Any, request: Any) -> None:
        self._manager = manager
        self._request = request

    async def materialize_request_runtime_model_if_needed(
        self,
        *,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        request: TaskExecutionRequest,
    ) -> TaskExecutionRequest:
        params = dict(request.resolved_params or {})
        plugin_params_raw = params.get("plugin")
        plugin_params = dict(plugin_params_raw) if isinstance(plugin_params_raw, dict) else {}
        current_model_source = str(plugin_params.get("model_source") or "").strip().lower()
        runtime_artifact_visible = current_model_source == "runtime_artifact"

        if not runtime_requirements.requires_trained_model:
            if not runtime_artifact_visible:
                return request
            plugin_params.pop("model_source", None)
            plugin_params.pop("model_custom_ref", None)
            params["plugin"] = plugin_params
            raw_payload = dict(request.raw_payload)
            raw_payload["resolved_params"] = params
            return replace(request, resolved_params=params, raw_payload=raw_payload)

        artifact_name = str(runtime_requirements.primary_model_artifact_name or "best.pt").strip() or "best.pt"
        runtime_model_ref = self._extract_runtime_model_ref_from_params(
            request_params=params,
            default_artifact_name=artifact_name,
        )
        if runtime_model_ref is None:
            if not runtime_artifact_visible:
                return request
            plugin_params.pop("model_source", None)
            plugin_params.pop("model_custom_ref", None)
            params["plugin"] = plugin_params
            raw_payload = dict(request.raw_payload)
            raw_payload["resolved_params"] = params
            return replace(request, resolved_params=params, raw_payload=raw_payload)

        local_model_path: Path | None = None
        linked = workspace.link_shared_model_to_step(artifact_name)
        if linked is not None and linked.exists():
            local_model_path = linked
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "训练模型已在插件解析前就绪 "
                        f"source=shared artifact={artifact_name} path={linked}"
                    ),
                },
            )
        else:
            local_model_path = await self._materialize_runtime_model_ref(
                workspace=workspace,
                emitter=emitter,
                runtime_model_ref=runtime_model_ref,
            )
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "训练模型已在插件解析前就绪 "
                        f"source=runtime_ref artifact={runtime_model_ref['artifact_name']} path={local_model_path}"
                    ),
                },
            )

        plugin_params["model_source"] = "custom_local"
        plugin_params["model_custom_ref"] = str(local_model_path)
        params["plugin"] = plugin_params
        raw_payload = dict(request.raw_payload)
        raw_payload["resolved_params"] = params
        return replace(request, resolved_params=params, raw_payload=raw_payload)

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
                        f"训练模型已就绪 source=shared artifact={artifact_name} path={linked}"
                    ),
                },
            )
            return

        runtime_model_ref = self._extract_runtime_model_ref(
            bound_plan=bound_plan,
            default_artifact_name=artifact_name,
        )
        if runtime_model_ref is not None:
            local_model_path = await self._materialize_runtime_model_ref(
                workspace=workspace,
                emitter=emitter,
                runtime_model_ref=runtime_model_ref,
            )
            bound_plan.effective_plugin_params["model_source"] = "custom_local"
            bound_plan.effective_plugin_params["model_custom_ref"] = str(local_model_path)
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "训练模型已就绪 "
                        f"source=runtime_ref artifact={runtime_model_ref['artifact_name']} path={local_model_path}"
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
                        f"训练模型已就绪 source=remote artifact={artifact_name} model_source={model_source}"
                    ),
                },
            )
            return

        message = (
            f"训练模型必需但不可用: "
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
                "message": f"{message}; STRICT_TRAIN_MODEL_HANDOFF=false，启用回退",
            },
        )

    @staticmethod
    def _extract_runtime_model_ref(
        *,
        bound_plan: BoundExecutionPlan,
        default_artifact_name: str,
    ) -> dict[str, str] | None:
        request_params = (
            bound_plan.plan.request.resolved_params
            if isinstance(bound_plan.plan.request.resolved_params, dict)
            else {}
        )
        return PipelineStageService._extract_runtime_model_ref_from_params(
            request_params=request_params,
            default_artifact_name=default_artifact_name,
        )

    @staticmethod
    def _extract_runtime_model_ref_from_params(
        *,
        request_params: dict[str, Any],
        default_artifact_name: str,
    ) -> dict[str, str] | None:
        runtime_refs_raw = request_params.get("_runtime_artifact_refs")
        runtime_refs = runtime_refs_raw if isinstance(runtime_refs_raw, dict) else {}
        model_raw = runtime_refs.get("model")
        model_ref = model_raw if isinstance(model_raw, dict) else {}
        if not model_ref:
            return None
        artifact_name = str(
            model_ref.get("artifact_name")
            or model_ref.get("artifactName")
            or default_artifact_name
            or "best.pt"
        ).strip() or "best.pt"
        source_task_id = str(model_ref.get("source_task_id") or model_ref.get("sourceTaskId") or "").strip()
        model_id = str(model_ref.get("model_id") or model_ref.get("modelId") or "").strip()
        if not source_task_id and not model_id:
            return None
        return {
            "artifact_name": artifact_name,
            "source_task_id": source_task_id,
            "model_id": model_id,
        }

    async def _materialize_runtime_model_ref(
        self,
        *,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_model_ref: dict[str, str],
    ) -> Path:
        artifact_name = str(runtime_model_ref.get("artifact_name") or "best.pt").strip() or "best.pt"
        source_task_id = str(runtime_model_ref.get("source_task_id") or "").strip()
        model_id = str(runtime_model_ref.get("model_id") or "").strip()
        ticket = await self._manager.request_download_ticket(
            task_id=self._request.task_id,
            source_task_id=source_task_id or None,
            model_id=model_id or None,
            artifact_name=artifact_name,
        )
        download_url = str(ticket.download_url or "").strip()
        if not download_url:
            raise RuntimeError(
                f"download ticket missing download_url artifact={artifact_name} "
                f"source_task_id={source_task_id or '-'} model_id={model_id or '-'}"
            )

        storage_uri = str(ticket.storage_uri or "").strip()
        source_ref = source_task_id or model_id or "runtime-artifact"
        cache_key = hashlib.sha256(
            f"{source_ref}|{artifact_name}|{storage_uri or download_url}".encode("utf-8")
        ).hexdigest()
        suffix = Path(artifact_name).suffix or ".bin"
        cache_path = workspace.cache_dir / f"runtime-model-{cache_key}{suffix}"
        if not cache_path.exists():
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        "开始下载运行时模型制品 "
                        f"artifact={artifact_name} source_task_id={source_task_id or '-'} model_id={model_id or '-'}"
                    ),
                },
            )
            tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            tmp_path.unlink(missing_ok=True)
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("GET", download_url, headers=dict(ticket.headers or {})) as response:
                    response.raise_for_status()
                    with tmp_path.open("wb") as file_obj:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
            tmp_path.rename(cache_path)
        return workspace.cache_model_artifact(artifact_name, cache_path, source_ref)

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
            if self._request.task_type == "score":
                return await self._run_score_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    runtime_requirements=runtime_requirements,
                    bound_plan=bound_plan,
                )

            if self._request.task_type == "predict":
                return await self._run_predict_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    runtime_requirements=runtime_requirements,
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

            raise RuntimeError(f"task_type 路由未实现: {self._request.task_type}")
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.EXECUTE,
                default_code=TaskErrorCode.EXECUTION_FAILED,
                exc=exc,
                message=f"任务执行失败 task_id={self._request.task_id}: {exc}",
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
            await emitter.emit("log", {"level": "INFO", "message": f"生效训练参数: {params_snapshot}"})
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
                message=f"准备数据失败 task_id={self._request.task_id}: {exc}",
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
                        f"运行时要求跳过 prepare_data task_type={self._request.task_type}"
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
                            "message": f"轮次共享数据缓存命中 fingerprint={fingerprint}",
                        },
                    )
                    return set()
            except Exception as exc:
                await emitter.emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": f"轮次共享数据缓存恢复失败 fingerprint={fingerprint} error={exc}",
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
                        "message": f"轮次共享数据缓存已写入 fingerprint={fingerprint} path={cached_path}",
                    },
                )
            except Exception as exc:
                await emitter.emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": f"轮次共享数据缓存写入失败 fingerprint={fingerprint} error={exc}",
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
            "version": 2,
            "round_id": self._request.round_id,
            "attempt": self._request.attempt,
            "project_id": self._request.project_id,
            "input_commit_id": self._request.input_commit_id,
            "plugin_id": self._request.plugin_id,
            "task_type": self._request.task_type,
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
                    "message": f"轮次共享模型缓存跳过: 未找到主制品 artifact={artifact_name}",
                },
            )
            return

        source_path = Path(primary_artifact.path)
        if not source_path.exists():
            await emitter.emit(
                "log",
                {
                    "level": "WARN",
                    "message": f"轮次共享模型缓存跳过: 制品文件缺失 artifact={artifact_name} path={source_path}",
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
                "message": f"轮次共享模型缓存已写入 artifact={artifact_name} path={cached_path}",
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
        candidates = await self._collect_sampling_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
            bound_plan=bound_plan,
            candidate_limit_mode="topk",
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

    async def _run_score_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        protected = await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        candidates = await self._collect_sampling_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
            bound_plan=bound_plan,
            candidate_limit_mode="review_pool",
        )
        candidates = normalize_prediction_candidates(candidates)
        metrics = {"score_candidate_count": float(len(candidates))}
        return metrics, {}, candidates, []

    async def _run_predict_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        runtime_requirements: TaskRuntimeRequirements,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        protected = await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            bound_plan=bound_plan,
        )
        candidates = await self._collect_predict_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
            bound_plan=bound_plan,
        )
        candidates = normalize_prediction_candidates(candidates)
        metrics = {"predict_candidate_count": float(len(candidates))}
        return metrics, {}, candidates, []

    async def _collect_sampling_candidates(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        protected: set[str],
        bound_plan: BoundExecutionPlan,
        candidate_limit_mode: str,
    ) -> list[dict[str, Any]]:
        mode = self._request.mode
        if mode == "manual":
            await emitter.emit("log", {"level": "INFO", "message": "手动模式：跳过采样"})
            return []

        skip_sampling = bool(self._request.resolved_params.get("skip_sampling", False))
        if skip_sampling:
            await emitter.emit("log", {"level": "INFO", "message": "skip_sampling=true，跳过采样"})
            return []

        sampling_cfg = self._request.resolved_params.get("sampling")
        sampling_cfg = dict(sampling_cfg) if isinstance(sampling_cfg, dict) else {}
        strategy = str(sampling_cfg.get("strategy") or self._request.query_strategy or "").strip()
        if not strategy:
            await emitter.emit("log", {"level": "INFO", "message": "采样策略为空，跳过采样"})
            return []
        topk = int(sampling_cfg.get("topk", self._request.resolved_params.get("topk", 200)))
        review_pool_size = int(sampling_cfg.get("review_pool_size", 0) or 0)
        if review_pool_size <= 0:
            review_pool_multiplier = int(sampling_cfg.get("review_pool_multiplier", 3) or 3)
            review_pool_multiplier = max(1, review_pool_multiplier)
            review_pool_size = max(topk, topk * review_pool_multiplier)
        if candidate_limit_mode == "review_pool":
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
            query_type="unlabeled_samples",
            topk=candidate_limit,
            context=bound_plan.execution_context,
        )

    async def _collect_predict_candidates(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: Any,
        protected: set[str],
        bound_plan: BoundExecutionPlan,
    ) -> list[dict[str, Any]]:
        if "sampling" in self._request.resolved_params:
            raise RuntimeError(
                "predict 任务包含已废弃的 params.sampling；请重新创建预测任务"
            )
        predict_cfg = self._request.resolved_params.get("predict")
        predict_cfg = dict(predict_cfg) if isinstance(predict_cfg, dict) else {}
        predict_params = dict(bound_plan.effective_plugin_params)
        predict_params.update(predict_cfg)
        runtime_context = bound_plan.plan.runtime_context
        predict_params["sampling_seed"] = int(
            predict_params.get("sampling_seed", runtime_context.sampling_seed)
        )
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": "预测推理采集器已启用 query_type=samples",
            },
        )
        return await self._manager.collect_prediction_candidates_streaming(
            plugin=plugin,
            workspace=workspace,
            task_id=self._request.task_id,
            project_id=self._request.project_id,
            commit_id=self._request.input_commit_id,
            params=predict_params,
            protected=protected,
            query_type="samples",
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
                message = f"制品={artifact.name} 必需={required} 错误={exc}"
                if required:
                    raise wrap_task_error(
                        stage=TaskStage.FINALIZE,
                        default_code=TaskErrorCode.ARTIFACT_UPLOAD_FAILED,
                        exc=exc,
                        message=f"必需制品上传失败: {message}",
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
