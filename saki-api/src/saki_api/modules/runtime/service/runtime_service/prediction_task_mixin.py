"""Prediction task orchestration mixin."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from saki_ir import IRValidationError, normalize_prediction_candidate, normalize_prediction_snapshot
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.annotation.repo.draft import AnnotationDraftRepository
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.runtime.domain.model_class_schema import ModelClassSchema
from saki_api.modules.runtime.domain.prediction_item import PredictionItem
from saki_api.modules.runtime.domain.prediction import Prediction
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.runtime.service.runtime_service.prediction_label_resolver import (
    PredictionLabelResolver,
    PredictionResolveError,
)
from saki_api.modules.shared.modeling.enums import (
    CommitSampleReviewState,
    RuntimeTaskKind,
    RuntimeTaskStatus,
    RuntimeTaskType,
    RuntimeMaintenanceMode,
)
from saki_api.modules.system.service.system_settings_reader import system_settings_reader


class PredictionTaskMixin:
    @staticmethod
    def _safe_uuid(raw: Any) -> uuid.UUID | None:
        if raw is None:
            return None
        try:
            return uuid.UUID(str(raw))
        except Exception:
            return None

    @staticmethod
    def _safe_float(raw: Any, *, default: float = 0.0) -> float:
        try:
            return float(raw)
        except Exception:
            return float(default)

    @staticmethod
    def _prediction_resolve_error_from_ir(
        exc: IRValidationError,
        *,
        sample_id: str = "",
    ) -> PredictionResolveError:
        issue = exc.issues[0] if exc.issues else None
        code = str(issue.code if issue else "IR_PREDICTION_FIELD_TYPE")
        if issue is None:
            message = exc.to_message()
        else:
            issue_path = str(issue.path or "<root>")
            message = f"{issue.message} (path={issue_path})"
        return PredictionResolveError(
            code=code,
            message=message,
            sample_id=sample_id,
        )

    @staticmethod
    def _prediction_entries_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(snapshot, dict):
            return []
        for key in ("base_predictions", "predictions"):
            rows = snapshot.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, dict)]
        return []

    async def _resolve_branch_name(self, branch_id: uuid.UUID) -> str:
        return (await self.project_gateway.get_branch_name(branch_id)) or "master"

    @staticmethod
    def _prediction_scope_status(*, scope_type: str, scope_payload: dict[str, Any]) -> str:
        if scope_type != "sample_status":
            raise BadRequestAppException("scope_type must be sample_status")
        status = str(scope_payload.get("status") or "all").strip().lower()
        if status not in {"all", "unlabeled", "labeled", "draft"}:
            raise BadRequestAppException("scope_payload.status must be one of all/unlabeled/labeled/draft")
        return status

    async def _resolve_artifact_download_url(self, *, uri: str, expires_in_hours: int = 6) -> str:
        normalized = str(uri or "").strip()
        if not normalized:
            raise BadRequestAppException("artifact uri is empty")
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        if normalized.startswith("s3://"):
            _, _, bucket_and_path = normalized.partition("s3://")
            _, _, object_path = bucket_and_path.partition("/")
            if not object_path:
                raise BadRequestAppException(f"invalid s3 uri: {normalized}")
            return self.storage.get_presigned_url(
                object_name=object_path,
                expires_delta=timedelta(hours=max(1, expires_in_hours)),
            )
        raise BadRequestAppException(f"unsupported artifact uri: {normalized}")


    @staticmethod
    def _match_artifact_payload(
        *,
        artifacts: dict[str, Any] | None,
        artifact_name: str,
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(artifacts, dict):
            return None
        target = str(artifact_name or "").strip()
        if not target:
            return None

        exact = artifacts.get(target)
        if isinstance(exact, dict):
            return target, dict(exact)

        target_norm = target.lower()
        for raw_key, raw_value in artifacts.items():
            if not isinstance(raw_value, dict):
                continue
            key = str(raw_key or "").strip()
            if not key:
                continue
            if key.lower() == target_norm:
                return key, dict(raw_value)
            leaf = key.rsplit("/", 1)[-1]
            if leaf.lower() == target_norm:
                return key, dict(raw_value)
        return None

    async def _resolve_prediction_model_artifact(
        self,
        *,
        project_id: uuid.UUID,
        plugin_id: str,
        model_id: uuid.UUID,
        artifact_name: str,
    ) -> tuple[uuid.UUID, str, str]:
        resolved_artifact_name = str(artifact_name or "best.pt").strip() or "best.pt"
        model = await self.model_repo.get_by_id_or_raise(model_id)
        if model.project_id != project_id:
            raise BadRequestAppException("model_id does not belong to project")
        if str(model.plugin_id or "").strip() != plugin_id:
            raise BadRequestAppException("plugin_id mismatch with model.plugin_id")
        artifact_match = self._match_artifact_payload(
            artifacts=model.artifacts if isinstance(model.artifacts, dict) else {},
            artifact_name=resolved_artifact_name,
        )
        if artifact_match is None:
            raise BadRequestAppException(f"model artifact '{resolved_artifact_name}' not found")
        matched_artifact_name, artifact = artifact_match
        uri = str(artifact.get("uri") or "")
        return model.id, await self._resolve_artifact_download_url(uri=uri), matched_artifact_name

    @staticmethod
    def _normalize_class_name(raw: Any) -> str:
        text = str(raw or "").strip().lower()
        return " ".join(text.split())

    @staticmethod
    def _hash_model_class_schema(rows: list[ModelClassSchema]) -> str:
        payload = [
            {
                "class_index": int(item.class_index),
                "label_id": str(item.label_id),
                "class_name_norm": str(item.class_name_norm or ""),
            }
            for item in rows
        ]
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _load_model_class_schema_rows(self, *, model_id: uuid.UUID) -> list[ModelClassSchema]:
        rows = await self.model_class_schema_repo.list_by_model(model_id)
        if not rows:
            raise BadRequestAppException(
                "[PREDICTION_SCHEMA_MISSING] model class schema is not found (phase=prediction_resolve)"
            )
        return rows

    async def _build_prediction_binding_from_model(
        self,
        *,
        model_id: uuid.UUID,
    ) -> tuple[str, list[str], dict[str, str]]:
        rows = await self._load_model_class_schema_rows(model_id=model_id)
        max_index = max(int(item.class_index) for item in rows)
        by_index: list[str] = ["" for _ in range(max_index + 1)]
        by_name: dict[str, str] = {}
        for item in rows:
            idx = int(item.class_index)
            if idx < 0:
                raise BadRequestAppException(
                    "[PREDICTION_SCHEMA_MISSING] invalid class_index in model class schema (phase=prediction_resolve)"
                )
            by_index[idx] = str(item.label_id)
            name_norm = self._normalize_class_name(item.class_name_norm or item.class_name)
            if name_norm:
                by_name[name_norm] = str(item.label_id)

        if any(not item for item in by_index):
            raise BadRequestAppException(
                "[PREDICTION_SCHEMA_MISSING] class_index mapping is discontinuous (phase=prediction_resolve)"
            )

        schema_hash = str(rows[0].schema_hash or "").strip() or self._hash_model_class_schema(rows)
        return schema_hash, by_index, by_name

    async def _prediction_resolver_for_prediction(self, *, prediction_id: uuid.UUID) -> PredictionLabelResolver:
        binding = await self.prediction_binding_repo.get_by_prediction_id(prediction_id)
        if binding is None:
            raise PredictionResolveError(
                code="PREDICTION_SCHEMA_MISSING",
                message="prediction binding is not found",
            )
        return PredictionLabelResolver.from_binding(binding)

    async def _filter_candidates_by_sample_scope(
        self,
        *,
        project_id: uuid.UUID,
        target_branch_id: uuid.UUID,
        base_commit_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        scope_type: str,
        scope_payload: dict[str, Any],
        candidates: list[TaskCandidateItem],
    ) -> list[TaskCandidateItem]:
        status = self._prediction_scope_status(scope_type=scope_type, scope_payload=scope_payload)
        if status == "all":
            return candidates

        sample_ids = [row.sample_id for row in candidates]
        if not sample_ids:
            return candidates

        if status in {"labeled", "unlabeled"}:
            labeled_sample_ids: set[uuid.UUID] = set()
            if base_commit_id is not None:
                labeled_sample_ids = set(
                    await self.annotation_gateway.list_labeled_sample_ids_at_commit(
                        commit_id=base_commit_id,
                        sample_ids=sample_ids,
                    )
                )
            allow_ids = labeled_sample_ids if status == "labeled" else (set(sample_ids) - labeled_sample_ids)
            return [row for row in candidates if row.sample_id in allow_ids]

        if actor_user_id is None:
            raise BadRequestAppException("actor user is required when scope_payload.status=draft")
        branch_row = await self.project_gateway.get_branch_in_project(
            branch_id=target_branch_id,
            project_id=project_id,
        )
        if branch_row is None or branch_row.project_id != project_id:
            raise BadRequestAppException("target branch not found when filtering draft scope")
        draft_sample_ids = set(
            await self.annotation_gateway.list_draft_sample_ids(
                project_id=project_id,
                user_id=actor_user_id,
                branch_name=branch_row.name,
                sample_ids=sample_ids,
            )
        )
        return [row for row in candidates if row.sample_id in draft_sample_ids]

    @staticmethod
    def _annotation_to_draft_payload_row(annotation: Annotation) -> dict[str, Any]:
        return {
            "id": str(annotation.id),
            "project_id": str(annotation.project_id),
            "sample_id": str(annotation.sample_id),
            "label_id": str(annotation.label_id),
            "group_id": str(annotation.group_id),
            "lineage_id": str(annotation.lineage_id),
            "parent_id": str(annotation.parent_id) if annotation.parent_id else None,
            "view_role": str(annotation.view_role or "main"),
            "type": str(annotation.type.value if hasattr(annotation.type, "value") else annotation.type),
            "source": str(annotation.source.value if hasattr(annotation.source, "value") else annotation.source),
            "geometry": dict(annotation.geometry or {}),
            "attrs": dict(annotation.attrs or {}),
            "confidence": float(annotation.confidence or 0.0),
            "annotator_id": str(annotation.annotator_id) if annotation.annotator_id else None,
        }

    async def _load_commit_annotations_by_sample(
        self,
        *,
        commit_id: uuid.UUID | None,
        sample_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        if commit_id is None or not sample_ids:
            return {}
        rows = await self.prediction_query_repo.list_commit_annotations_by_samples(
            commit_id=commit_id,
            sample_ids=sample_ids,
        )
        result: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for sample_id, annotation in rows:
            result.setdefault(sample_id, []).append(self._annotation_to_draft_payload_row(annotation))
        return result

    async def _build_prediction_rows_from_candidates(
        self,
        *,
        prediction_id: uuid.UUID,
        candidates: list[TaskCandidateItem],
    ) -> list[dict[str, Any]]:
        resolver = await self._prediction_resolver_for_prediction(prediction_id=prediction_id)
        prediction_rows: list[dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            raw_candidate: dict[str, Any] = {
                "sample_id": str(candidate.sample_id),
                "score": float(candidate.score or 0.0),
                "reason": dict(candidate.reason or {}) if isinstance(candidate.reason, dict) else {},
            }
            if isinstance(candidate.prediction_snapshot, dict):
                raw_candidate["prediction_snapshot"] = dict(candidate.prediction_snapshot or {})
            try:
                normalized_candidate = normalize_prediction_candidate(raw_candidate, path=f"candidate[{idx}]")
            except IRValidationError as exc:
                raise self._prediction_resolve_error_from_ir(exc, sample_id=str(candidate.sample_id)) from exc

            reason_payload = normalized_candidate.get("reason")
            reason_payload = dict(reason_payload) if isinstance(reason_payload, dict) else {}
            snapshot_raw = normalized_candidate.get("prediction_snapshot")
            if snapshot_raw is None:
                snapshot_raw = reason_payload.get("prediction_snapshot")
            snapshot = dict(snapshot_raw) if isinstance(snapshot_raw, dict) else {}
            prediction_entries = self._prediction_entries_from_snapshot(snapshot)
            if not prediction_entries:
                continue
            primary_prediction = prediction_entries[0]
            decision = resolver.resolve(
                snapshot=snapshot,
                prediction=primary_prediction,
                sample_id=str(candidate.sample_id),
            )
            geometry_raw = primary_prediction.get("geometry")
            geometry = dict(geometry_raw) if isinstance(geometry_raw, dict) else {}
            attrs_raw = primary_prediction.get("attrs")
            attrs = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}
            confidence = self._safe_float(
                primary_prediction.get("confidence"),
                default=float(normalized_candidate.get("score") or candidate.score or 0.0),
            )

            meta_payload = dict(snapshot or {})
            if prediction_entries and not isinstance(meta_payload.get("base_predictions"), list) and not isinstance(
                meta_payload.get("predictions"), list
            ):
                meta_payload["predictions"] = prediction_entries

            prediction_rows.append(
                {
                    "sample_id": candidate.sample_id,
                    "rank": int(candidate.rank or 0),
                    "score": float(candidate.score or 0.0),
                    "label_id": decision.label_id,
                    "geometry": geometry,
                    "attrs": attrs,
                    "confidence": confidence,
                    "meta": meta_payload,
                }
            )
        return prediction_rows

    @staticmethod
    def _prediction_status_from_task(task_status: RuntimeTaskStatus | None) -> str:
        if task_status in {
            RuntimeTaskStatus.DISPATCHING,
            RuntimeTaskStatus.SYNCING_ENV,
            RuntimeTaskStatus.PROBING_RUNTIME,
            RuntimeTaskStatus.BINDING_DEVICE,
            RuntimeTaskStatus.RUNNING,
            RuntimeTaskStatus.RETRYING,
        }:
            return "running"
        if task_status in {RuntimeTaskStatus.FAILED, RuntimeTaskStatus.CANCELLED, RuntimeTaskStatus.SKIPPED}:
            return "failed"
        if task_status == RuntimeTaskStatus.SUCCEEDED:
            return "materializing"
        return "queued"

    @staticmethod
    def _attach_task_projection(prediction: Prediction, step: Step | None) -> Prediction:
        del step
        return prediction

    async def _task_result_candidates(self, *, task_id: uuid.UUID) -> list[TaskCandidateItem]:
        return await self.task_candidate_repo.list_by_task(task_id)

    @transactional
    async def create_prediction(
        self,
        *,
        project_id: uuid.UUID,
        payload: dict[str, Any],
        actor_user_id: uuid.UUID | None,
    ) -> Prediction:
        maintenance_mode = await system_settings_reader.get_runtime_maintenance_mode()
        if maintenance_mode != RuntimeMaintenanceMode.NORMAL:
            raise BadRequestAppException(f"runtime maintenance mode={maintenance_mode.value}")
        if actor_user_id is None:
            raise BadRequestAppException("actor user is required when creating prediction")

        explicit_model_id = self._safe_uuid(payload.get("model_id"))
        explicit_artifact_name = str(payload.get("artifact_name") or "best.pt").strip() or "best.pt"
        legacy_fields = sorted(
            field_name for field_name in ("plugin_id", "model_source", "target_round_id") if field_name in payload
        )
        if legacy_fields:
            raise BadRequestAppException(
                f"legacy prediction fields are not supported: {', '.join(legacy_fields)}"
            )
        if explicit_model_id is None:
            raise BadRequestAppException("model_id is required")

        target_branch_id = self._safe_uuid(payload.get("target_branch_id"))
        if target_branch_id is None:
            raise BadRequestAppException("target_branch_id is required")
        target_branch = await self.project_gateway.get_branch_in_project(
            branch_id=target_branch_id,
            project_id=project_id,
        )
        if target_branch is None or target_branch.project_id != project_id:
            raise BadRequestAppException("target_branch_id does not belong to project")

        base_commit_id = self._safe_uuid(payload.get("base_commit_id"))
        if base_commit_id is None:
            raise BadRequestAppException("base_commit_id is required")
        base_commit = await self.project_gateway.get_commit(base_commit_id)
        if base_commit is None or base_commit.project_id != project_id:
            raise BadRequestAppException("base_commit_id does not belong to project")

        model_probe = await self.model_repo.get_by_id_or_raise(explicit_model_id)
        if model_probe.project_id != project_id:
            raise BadRequestAppException("model_id does not belong to project")
        plugin_id = str(model_probe.plugin_id or "").strip()
        if not plugin_id:
            raise BadRequestAppException("model.plugin_id is required")
        model_id, model_download_url, artifact_name = await self._resolve_prediction_model_artifact(
            project_id=project_id,
            plugin_id=plugin_id,
            model_id=model_probe.id,
            artifact_name=explicit_artifact_name,
        )
        schema_hash, by_index, by_name = await self._build_prediction_binding_from_model(model_id=model_id)

        scope_type = str(payload.get("scope_type") or "sample_status").strip() or "sample_status"
        scope_payload = payload.get("scope_payload") if isinstance(payload.get("scope_payload"), dict) else {}
        self._prediction_scope_status(scope_type=scope_type, scope_payload=scope_payload)

        predict_conf_raw = payload.get("predict_conf")
        predict_conf: float | None = None
        if predict_conf_raw is not None:
            try:
                predict_conf = float(predict_conf_raw)
            except Exception as exc:
                raise BadRequestAppException("predict_conf must be a valid number") from exc
            if predict_conf < 0.0 or predict_conf > 1.0:
                raise BadRequestAppException("predict_conf must be in range [0, 1]")

        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        persisted_params = dict(params)
        if "sampling" in payload:
            raise BadRequestAppException("predict does not support sampling parameters")
        if "sampling" in params:
            raise BadRequestAppException("predict does not support sampling parameters")

        step_params = dict(params)
        plugin_params = step_params.get("plugin")
        plugin_params = dict(plugin_params) if isinstance(plugin_params, dict) else {}
        plugin_params["model_source"] = "custom_url"
        plugin_params["model_custom_ref"] = model_download_url
        plugin_params["artifact_name"] = artifact_name
        step_params["plugin"] = plugin_params

        predict_params = step_params.get("predict")
        predict_params = dict(predict_params) if isinstance(predict_params, dict) else {}
        if predict_conf is not None:
            predict_params["predict_conf"] = float(predict_conf)
        if predict_params:
            step_params["predict"] = predict_params
            persisted_params["predict"] = dict(predict_params)

        task_meta = {
            "plugin_id": plugin_id,
            "target_branch_id": str(target_branch_id),
            "base_commit_id": str(base_commit_id),
            "model_id": str(model_id),
            "schema_hash": schema_hash,
            "scope_type": scope_type,
            "scope_payload": dict(scope_payload),
            "predict_conf": predict_conf,
            "artifact_name": artifact_name,
        }
        persisted_params["_prediction_task"] = task_meta
        step_params["_prediction_task"] = task_meta

        task = await self.task_repo.create(
            {
                "project_id": project_id,
                "kind": RuntimeTaskKind.PREDICTION,
                "task_type": RuntimeTaskType.PREDICT,
                "status": RuntimeTaskStatus.READY,
                "plugin_id": plugin_id,
                "input_commit_id": base_commit_id,
                "resolved_params": dict(step_params),
                "assigned_executor_id": None,
                "attempt": 1,
                "max_attempts": 1,
                "last_error": None,
            }
        )

        prediction = await self.prediction_repo.create(
            {
                "project_id": project_id,
                "plugin_id": plugin_id,
                "model_id": model_id,
                "base_commit_id": base_commit_id,
                "scope_type": scope_type,
                "scope_payload": dict(scope_payload),
                "status": "queued",
                "total_items": 0,
                "params": persisted_params,
                "created_by": actor_user_id,
                "last_error": None,
                "task_id": task.id,
            }
        )
        await self.prediction_binding_repo.upsert(
            prediction_id=prediction.id,
            model_id=model_id,
            schema_hash=schema_hash,
            by_index_json=by_index,
            by_name_json=by_name,
        )
        return self._attach_task_projection(prediction, None)

    @transactional
    async def settle_prediction_task(self, *, prediction_id: uuid.UUID) -> Prediction:
        prediction = await self.prediction_repo.get_by_id_or_raise(prediction_id)
        task = await self.task_repo.get_by_id(prediction.task_id)
        if task is None:
            failed = await self.prediction_repo.update(
                prediction.id,
                {
                    "status": "failed",
                    "last_error": "prediction task not found",
                },
            )
            return self._attach_task_projection(failed or prediction, None)

        task_state = task.status if isinstance(task.status, RuntimeTaskStatus) else self._parse_enum(
            RuntimeTaskStatus,
            task.status,
            field_name="task.status",
            default=RuntimeTaskStatus.PENDING,
        )

        if task_state == RuntimeTaskStatus.SUCCEEDED and str(prediction.status or "").lower() not in {"ready", "applied"}:
            prediction = await self.prediction_repo.update(
                prediction.id,
                {
                    "status": "materializing",
                    "last_error": None,
                },
            ) or prediction

            task_meta = prediction.params.get("_prediction_task") if isinstance(prediction.params, dict) else {}
            target_branch_id = self._safe_uuid(task_meta.get("target_branch_id")) if isinstance(task_meta, dict) else None
            if target_branch_id is None:
                raise BadRequestAppException("prediction is missing target_branch_id")
            base_commit_id = prediction.base_commit_id or task.input_commit_id
            if base_commit_id is None:
                branch_row = await self.project_gateway.get_branch(target_branch_id)
                base_commit_id = branch_row.head_commit_id if branch_row else None

            source_candidates = await self._task_result_candidates(task_id=task.id)
            filtered_candidates = await self._filter_candidates_by_sample_scope(
                project_id=prediction.project_id,
                target_branch_id=target_branch_id,
                base_commit_id=base_commit_id,
                actor_user_id=prediction.created_by,
                scope_type=str(prediction.scope_type or "sample_status"),
                scope_payload=dict(prediction.scope_payload or {}),
                candidates=source_candidates,
            )
            try:
                prediction_rows = await self._build_prediction_rows_from_candidates(
                    prediction_id=prediction.id,
                    candidates=filtered_candidates,
                )
            except PredictionResolveError as exc:
                prediction = await self.prediction_repo.update(
                    prediction.id,
                    {
                        "status": "failed",
                        "last_error": exc.to_error_message(),
                    },
                ) or prediction
                return self._attach_task_projection(prediction, None)
            await self.prediction_item_repo.replace_rows(
                prediction_id=prediction.id,
                rows=prediction_rows,
            )
            prediction = await self.prediction_repo.update(
                prediction.id,
                {
                    "status": "ready",
                    "total_items": int(len(prediction_rows)),
                    "last_error": None,
                },
            ) or prediction
            return self._attach_task_projection(prediction, None)

        desired_status = self._prediction_status_from_task(task_state)
        if desired_status == "failed":
            desired_last_error = str(task.last_error or "")
        else:
            desired_last_error = None
        if str(prediction.status or "").lower() not in {"ready", "applied"} and (
            str(prediction.status or "").lower() != desired_status
            or str(prediction.last_error or "") != str(desired_last_error or "")
        ):
            prediction = await self.prediction_repo.update(
                prediction.id,
                {
                    "status": desired_status,
                    "last_error": desired_last_error,
                },
            ) or prediction
        return self._attach_task_projection(prediction, None)

    async def list_predictions(self, *, project_id: uuid.UUID, limit: int = 100) -> list[Prediction]:
        rows = await self.prediction_repo.list_by_project(project_id=project_id, limit=limit)
        settled_rows: list[Prediction] = []
        for row in rows:
            settled_rows.append(await self.settle_prediction_task(prediction_id=row.id))
        return settled_rows

    async def list_prediction_tasks(self, *, project_id: uuid.UUID, limit: int = 100) -> list[Prediction]:
        return await self.list_predictions(project_id=project_id, limit=limit)

    async def get_prediction_task(self, *, task_id: uuid.UUID) -> Prediction:
        prediction = await self.prediction_repo.get_by_task_id(task_id)
        if prediction is None:
            raise NotFoundAppException("prediction task not found")
        return await self.settle_prediction_task(prediction_id=prediction.id)

    async def get_prediction_detail(
        self,
        *,
        prediction_id: uuid.UUID,
        item_limit: int = 2000,
    ) -> tuple[Prediction, list[PredictionItem]]:
        prediction = await self.settle_prediction_task(prediction_id=prediction_id)
        items = await self.prediction_item_repo.list_by_prediction(prediction_id, limit=item_limit)
        return prediction, items

    @transactional
    async def apply_prediction(
        self,
        *,
        prediction_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        branch_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if actor_user_id is None:
            raise BadRequestAppException("actor user is required when applying prediction")
        prediction = await self.settle_prediction_task(prediction_id=prediction_id)
        project_id = prediction.project_id
        items = await self.prediction_item_repo.list_by_prediction(prediction_id, limit=100000)
        if not items:
            return {
                "prediction_id": prediction.id,
                "applied_count": 0,
                "status": str(prediction.status or "ready"),
            }

        resolved_branch_name = str(branch_name or "").strip()
        branch_row: Branch | None = None
        if resolved_branch_name:
            branch_row = await self.project_gateway.get_branch_by_name(
                project_id=project_id,
                name=resolved_branch_name,
            )
            if branch_row is None:
                raise BadRequestAppException(f"branch '{resolved_branch_name}' not found in project")
        else:
            task_meta = prediction.params.get("_prediction_task") if isinstance(prediction.params, dict) else {}
            target_branch_id = self._safe_uuid(task_meta.get("target_branch_id")) if isinstance(task_meta, dict) else None
            if target_branch_id is not None:
                branch_row = await self.project_gateway.get_branch(target_branch_id)
        if branch_row is None:
            raise BadRequestAppException("target branch not found when applying prediction")

        resolved_branch_name = str(getattr(branch_row, "name", "") or "").strip() or "master"
        branch_head_commit_id: uuid.UUID | None = getattr(branch_row, "head_commit_id", None)
        try:
            resolver = await self._prediction_resolver_for_prediction(prediction_id=prediction_id)
        except PredictionResolveError as exc:
            prediction = await self.prediction_repo.update(
                prediction.id,
                {
                    "status": "failed",
                    "last_error": exc.to_error_message(),
                },
            ) or prediction
            return {
                "prediction_id": prediction.id,
                "applied_count": 0,
                "status": str(prediction.status or "failed"),
            }

        draft_repo = AnnotationDraftRepository(self.session)
        grouped_items: dict[uuid.UUID, list[PredictionItem]] = {}
        for row in items:
            grouped_items.setdefault(row.sample_id, []).append(row)
        committed_base_by_sample = await self._load_commit_annotations_by_sample(
            commit_id=branch_head_commit_id,
            sample_ids=list(grouped_items.keys()),
        )
        existing_drafts_by_sample = await self.prediction_query_repo.list_drafts_by_scope_and_samples(
            project_id=project_id,
            user_id=actor_user_id,
            branch_name=resolved_branch_name,
            sample_ids=list(grouped_items.keys()),
        )

        applied_count = 0
        for sample_id, group in grouped_items.items():
            existing = existing_drafts_by_sample.get(sample_id)
            existing_payload = dict(existing.payload or {}) if existing and isinstance(existing.payload, dict) else {}
            existing_annotations_raw = existing_payload.get("annotations")
            if existing is not None and isinstance(existing_annotations_raw, list):
                source_annotations = [dict(ann) for ann in existing_annotations_raw if isinstance(ann, dict)]
            else:
                source_annotations = list(committed_base_by_sample.get(sample_id, []))

            base_annotations = [
                ann
                for ann in source_annotations
                if str(ann.get("source") or "").strip().lower() != "model"
            ]

            model_annotations: list[dict[str, Any]] = []
            for prediction_item in sorted(group, key=lambda row: int(row.rank or 0)):
                snapshot_raw = dict(prediction_item.meta or {}) if isinstance(prediction_item.meta, dict) else {}
                try:
                    snapshot = normalize_prediction_snapshot(
                        snapshot_raw,
                        path=f"prediction_item[{int(prediction_item.rank or 0)}].meta",
                    )
                except IRValidationError as exc:
                    resolve_error = self._prediction_resolve_error_from_ir(exc, sample_id=str(sample_id))
                    prediction = await self.prediction_repo.update(
                        prediction.id,
                        {
                            "status": "failed",
                            "last_error": resolve_error.to_error_message(),
                        },
                    ) or prediction
                    return {
                        "prediction_id": prediction.id,
                        "applied_count": 0,
                        "status": str(prediction.status or "failed"),
                    }
                prediction_entries = self._prediction_entries_from_snapshot(snapshot)
                if not prediction_entries:
                    prediction = await self.prediction_repo.update(
                        prediction.id,
                        {
                            "status": "failed",
                            "last_error": (
                                "[PREDICTION_LABEL_UNRESOLVED] prediction_snapshot.base_predictions/predictions "
                                "is empty (phase=prediction_resolve)"
                            ),
                        },
                    ) or prediction
                    return {
                        "prediction_id": prediction.id,
                        "applied_count": 0,
                        "status": str(prediction.status or "failed"),
                    }

                for entry in prediction_entries:
                    prediction_payload = dict(entry) if isinstance(entry, dict) else {}
                    try:
                        decision = resolver.resolve(
                            snapshot=snapshot,
                            prediction=prediction_payload,
                            sample_id=str(sample_id),
                        )
                    except PredictionResolveError as exc:
                        prediction = await self.prediction_repo.update(
                            prediction.id,
                            {
                                "status": "failed",
                                "last_error": exc.to_error_message(),
                            },
                        ) or prediction
                        return {
                            "prediction_id": prediction.id,
                            "applied_count": 0,
                            "status": str(prediction.status or "failed"),
                        }
                    label_id = decision.label_id

                    geometry_raw = prediction_payload.get("geometry")
                    geometry = dict(geometry_raw) if isinstance(geometry_raw, dict) else {}
                    if not geometry:
                        continue

                    attrs_raw = prediction_payload.get("attrs")
                    attrs = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}
                    confidence = self._safe_float(
                        prediction_payload.get("confidence"),
                        default=float(prediction_item.confidence or prediction_item.score or 0.0),
                    )

                    annotation_id = str(uuid.uuid4())
                    annotation_type = "obb" if isinstance(geometry.get("obb"), dict) else "rect"
                    model_annotations.append(
                        {
                            "id": annotation_id,
                            "group_id": annotation_id,
                            "lineage_id": annotation_id,
                            "project_id": str(project_id),
                            "sample_id": str(sample_id),
                            "label_id": str(label_id),
                            "type": annotation_type,
                            "geometry": geometry,
                            "attrs": attrs,
                            "source": "model",
                            "confidence": confidence,
                            "annotator_id": str(actor_user_id),
                        }
                    )

            if not model_annotations:
                continue

            applied_count += len(model_annotations)
            if dry_run:
                continue

            payload_to_write = {
                **existing_payload,
                "annotations": base_annotations + model_annotations,
            }
            if existing is None:
                await draft_repo.create(
                    {
                        "project_id": project_id,
                        "sample_id": sample_id,
                        "user_id": actor_user_id,
                        "branch_name": resolved_branch_name,
                        "payload": payload_to_write,
                    }
                )
            else:
                await draft_repo.update(existing.id, {"payload": payload_to_write})

        if not dry_run:
            prediction = await self.prediction_repo.update(
                prediction.id,
                {
                    "status": "applied",
                },
            ) or prediction

        return {
            "prediction_id": prediction.id,
            "applied_count": int(applied_count),
            "status": str(prediction.status or ("ready" if dry_run else "applied")),
        }
