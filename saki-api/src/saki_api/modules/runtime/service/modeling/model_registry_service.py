"""
Model service for L3 model registry operations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import uuid
from pathlib import PurePosixPath
from typing import Any
from datetime import datetime, UTC, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.runtime.api.model import ModelCreateData, ModelPatch
from saki_api.modules.runtime.domain.model import Model
from saki_api.modules.runtime.repo.loop import LoopRepository
from saki_api.modules.runtime.repo.model import ModelRepository
from saki_api.modules.runtime.repo.model_class_schema import ModelClassSchemaRepository
from saki_api.modules.runtime.repo.round import RoundRepository
from saki_api.modules.runtime.repo.step import StepRepository
from saki_api.modules.runtime.repo.task import TaskRepository


@dataclass(slots=True)
class _ArtifactCandidate:
    name: str
    kind: str
    uri: str
    meta: dict[str, Any]
    step_id: uuid.UUID
    task_id: uuid.UUID
    step_index: int
    step_type: str


class ModelService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.round_repo = RoundRepository(session)
        self.loop_repo = LoopRepository(session)
        self.step_repo = StepRepository(session)
        self.task_repo = TaskRepository(session)
        self.repository = ModelRepository(session)
        self.model_class_schema_repo = ModelClassSchemaRepository(session)
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize_step_type(value: Any) -> str:
        text = str(value.value if hasattr(value, "value") else value).strip().lower()
        return text or "custom"

    @staticmethod
    def _normalize_status(value: str | None) -> str:
        status = str(value or "candidate").strip().lower()
        if status not in {"candidate", "production", "archived"}:
            raise BadRequestAppException("status must be one of candidate/production/archived")
        return status

    @staticmethod
    def _is_model_like_artifact(candidate: _ArtifactCandidate) -> bool:
        kind = str(candidate.kind or "").strip().lower()
        if kind in {"weights", "model_export"}:
            return True
        suffix = PurePosixPath(candidate.name).suffix.lower()
        return suffix in {".pt", ".onnx", ".engine", ".pth", ".ckpt", ".bin", ".safetensors"}

    @staticmethod
    def _is_eval_artifact(candidate: _ArtifactCandidate) -> bool:
        kind = str(candidate.kind or "").strip().lower()
        if candidate.step_type == "eval":
            return True
        if kind in {"report", "eval_artifact", "confusion_matrix", "confusion_matrix_normalized"}:
            return True
        name = candidate.name.lower()
        return "report" in name or "confusion" in name or name.startswith("eval_")

    @staticmethod
    def _is_class_schema_artifact(candidate: _ArtifactCandidate) -> bool:
        kind = str(candidate.kind or "").strip().lower()
        if kind == "class_schema":
            return True
        name = str(candidate.name or "").strip().lower()
        return name == "class_schema.json" or name.endswith("/class_schema.json")

    @staticmethod
    def _build_artifact_payload(candidate: _ArtifactCandidate) -> dict[str, Any]:
        meta = dict(candidate.meta or {})
        meta.setdefault("step_id", str(candidate.step_id))
        meta.setdefault("task_id", str(candidate.task_id))
        meta.setdefault("step_type", candidate.step_type)
        meta.setdefault("step_index", int(candidate.step_index))
        return {
            "kind": candidate.kind or "artifact",
            "uri": candidate.uri,
            "meta": meta,
        }

    @staticmethod
    def _find_candidate_by_name(
            *,
            candidates: dict[str, _ArtifactCandidate],
            artifact_name: str,
    ) -> _ArtifactCandidate | None:
        direct = candidates.get(artifact_name)
        if direct is not None:
            return direct
        target = artifact_name.strip().lower()
        for key, value in candidates.items():
            if key.strip().lower() == target:
                return value
        return None

    async def _collect_round_artifacts(self, round_id: uuid.UUID) -> dict[str, _ArtifactCandidate]:
        step_rows = await self.step_repo.list_by_round(round_id)
        task_ids = [step.task_id for step in step_rows if step.task_id is not None]
        task_rows = await self.task_repo.get_by_ids(task_ids) if task_ids else []
        task_by_id = {task.id: task for task in task_rows}
        collected: dict[str, _ArtifactCandidate] = {}
        for step in step_rows:
            if step.task_id is None:
                continue
            step_type = self._normalize_step_type(step.step_type)
            artifact_map: dict[str, Any] = {}
            task = task_by_id.get(step.task_id)
            params = task.resolved_params if task and isinstance(task.resolved_params, dict) else {}
            task_result_artifacts = params.get("_result_artifacts")
            if isinstance(task_result_artifacts, dict):
                artifact_map = task_result_artifacts
            if not artifact_map:
                continue
            for raw_name, raw_payload in artifact_map.items():
                name = self._normalize_text(raw_name)
                if not name:
                    continue
                if not isinstance(raw_payload, dict):
                    continue
                uri = self._normalize_text(raw_payload.get("uri"))
                if not uri:
                    continue
                kind = self._normalize_text(raw_payload.get("kind")) or "artifact"
                meta_raw = raw_payload.get("meta")
                meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
                collected[name] = _ArtifactCandidate(
                    name=name,
                    kind=kind,
                    uri=uri,
                    meta=meta,
                    step_id=step.id,
                    task_id=step.task_id,
                    step_index=int(step.step_index or 0),
                    step_type=step_type,
                )
        return collected

    def _pick_primary_artifact(
            self,
            *,
            candidates: dict[str, _ArtifactCandidate],
            primary_artifact_name: str | None,
    ) -> _ArtifactCandidate:
        if not candidates:
            raise BadRequestAppException("round has no downloadable artifacts")

        if primary_artifact_name:
            matched = self._find_candidate_by_name(candidates=candidates, artifact_name=primary_artifact_name)
            if matched is None:
                raise BadRequestAppException(f"primary artifact '{primary_artifact_name}' not found in round")
            return matched

        model_candidates = [item for item in candidates.values() if self._is_model_like_artifact(item)]
        if not model_candidates:
            fallback = self._find_candidate_by_name(candidates=candidates, artifact_name="best.pt")
            if fallback is not None:
                return fallback
            raise BadRequestAppException("no model-like artifact found on round")

        def _score(item: _ArtifactCandidate) -> tuple[int, int]:
            score = 0
            if item.step_type == "train":
                score += 100
            if item.kind.lower() == "weights":
                score += 40
            if item.kind.lower() == "model_export":
                score += 30
            if item.name.lower() == "best.pt":
                score += 20
            return score, int(item.step_index)

        return max(model_candidates, key=_score)

    def _build_publish_bundle(
            self,
            *,
            primary: _ArtifactCandidate,
            all_candidates: dict[str, _ArtifactCandidate],
    ) -> dict[str, dict[str, Any]]:
        payload: dict[str, dict[str, Any]] = {
            primary.name: self._build_artifact_payload(primary),
        }
        for item in all_candidates.values():
            if item.name == primary.name:
                continue
            if self._is_eval_artifact(item) or self._is_class_schema_artifact(item):
                payload[item.name] = self._build_artifact_payload(item)
        return payload

    @staticmethod
    def _normalize_class_name(value: Any) -> str:
        text = str(value or "").strip().lower()
        return " ".join(text.split())

    @classmethod
    def _extract_model_class_rows(
        cls,
        *,
        candidates: dict[str, _ArtifactCandidate],
    ) -> tuple[list[dict[str, Any]], str]:
        schema_candidate = next(
            (item for item in candidates.values() if cls._is_class_schema_artifact(item)),
            None,
        )
        if schema_candidate is None:
            return [], ""

        rows_raw = schema_candidate.meta.get("class_schema_rows") if isinstance(schema_candidate.meta, dict) else None
        if not isinstance(rows_raw, list):
            return [], ""

        rows: list[dict[str, Any]] = []
        for item in rows_raw:
            if not isinstance(item, dict):
                continue
            label_id = str(item.get("label_id") or "").strip()
            if not label_id:
                continue
            try:
                class_index = int(item.get("class_index"))
            except Exception:
                continue
            if class_index < 0:
                continue
            class_name = str(item.get("class_name") or f"class_{class_index}")
            class_name_norm = cls._normalize_class_name(item.get("class_name_norm") or class_name)
            rows.append(
                {
                    "class_index": class_index,
                    "label_id": uuid.UUID(label_id),
                    "class_name": class_name,
                    "class_name_norm": class_name_norm,
                }
            )

        if not rows:
            return [], ""

        rows.sort(key=lambda entry: int(entry["class_index"]))
        canonical = [
            {
                "class_index": int(item["class_index"]),
                "label_id": str(item["label_id"]),
                "class_name_norm": str(item["class_name_norm"]),
            }
            for item in rows
        ]
        encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        schema_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return rows, schema_hash

    async def _persist_model_class_schema(
        self,
        *,
        model_id: uuid.UUID,
        candidates: dict[str, _ArtifactCandidate],
    ) -> None:
        rows, schema_hash = self._extract_model_class_rows(candidates=candidates)
        if not rows:
            await self.model_class_schema_repo.replace_for_model(model_id=model_id, rows=[])
            return
        await self.model_class_schema_repo.replace_for_model(
            model_id=model_id,
            rows=[
                {
                    "class_index": int(item["class_index"]),
                    "label_id": item["label_id"],
                    "class_name": str(item["class_name"]),
                    "class_name_norm": str(item["class_name_norm"]),
                    "schema_hash": schema_hash,
                }
                for item in rows
            ],
        )

    @transactional
    async def publish_from_round(
            self,
            *,
            project_id: uuid.UUID,
            round_id: uuid.UUID,
            created_by: uuid.UUID | None,
            name: str | None,
            primary_artifact_name: str | None,
            version_tag: str | None,
            status: str | None,
    ) -> Model:
        round_row = await self.round_repo.get_by_id(round_id)
        if not round_row:
            raise NotFoundAppException(f"Round {round_id} not found")
        if round_row.project_id != project_id:
            raise BadRequestAppException("Round does not belong to this project")
        if str(round_row.state.value if hasattr(round_row.state, "value") else round_row.state).lower() != "completed":
            raise BadRequestAppException("only completed round can be published")

        all_candidates = await self._collect_round_artifacts(round_id)
        primary = self._pick_primary_artifact(
            candidates=all_candidates,
            primary_artifact_name=self._normalize_text(primary_artifact_name) or None,
        )
        normalized_status = self._normalize_status(status)

        loop = await self.loop_repo.get_by_id(round_row.loop_id)
        model_name = name or f"{loop.name if loop else 'loop'}-r{round_row.round_index}"
        parent_model_id = None

        resolved_version_tag = self._normalize_text(version_tag)
        if not resolved_version_tag:
            resolved_version_tag = f"r{int(round_row.round_index or 0)}-a{int(round_row.attempt_index or 1)}"

        existing = await self.repository.get_by_publish_key(
            project_id=project_id,
            source_round_id=round_row.id,
            primary_artifact_name=primary.name,
            version_tag=resolved_version_tag,
        )
        if existing is not None:
            return existing

        artifact_map = self._build_publish_bundle(primary=primary, all_candidates=all_candidates)
        publish_manifest = {
            "source_round_id": str(round_row.id),
            "round_index": int(round_row.round_index or 0),
            "attempt_index": int(round_row.attempt_index or 1),
            "primary_artifact_name": primary.name,
            "primary_task_id": str(primary.task_id),
            "included_artifacts": sorted(artifact_map.keys()),
            "published_at": datetime.now(UTC).isoformat(),
        }
        weights_path = primary.uri
        create_status = "candidate" if normalized_status == "production" else normalized_status

        create_data = ModelCreateData(
            project_id=project_id,
            source_commit_id=round_row.input_commit_id,
            source_round_id=round_row.id,
            source_task_id=primary.task_id,
            parent_model_id=parent_model_id,
            plugin_id=round_row.plugin_id,
            model_arch=loop.model_arch if loop else round_row.plugin_id,
            name=model_name,
            version_tag=resolved_version_tag,
            primary_artifact_name=primary.name,
            weights_path=weights_path,
            status=create_status,
            metrics=dict(round_row.final_metrics or {}),
            artifacts=artifact_map,
            publish_manifest=publish_manifest,
            created_by=created_by,
        )
        created = await self.repository.create(
            create_data.model_dump(exclude_none=True)
        )
        await self._persist_model_class_schema(model_id=created.id, candidates=all_candidates)
        if normalized_status == "production":
            created = await self.promote(model_id=created.id, target_status="production")
        return created

    async def list_by_project(
            self,
            project_id: uuid.UUID,
            *,
            limit: int = 100,
            offset: int = 0,
            status: str | None = None,
            plugin_id: str | None = None,
            source_round_id: uuid.UUID | None = None,
            q: str | None = None,
    ) -> list[Model]:
        normalized_status = self._normalize_text(status).lower() or None
        if normalized_status is not None and normalized_status not in {"candidate", "production", "archived"}:
            raise BadRequestAppException("status filter must be one of candidate/production/archived")
        return await self.repository.list_by_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
            status=normalized_status,
            plugin_id=self._normalize_text(plugin_id) or None,
            source_round_id=source_round_id,
            q=self._normalize_text(q) or None,
        )

    @transactional
    async def promote(self, model_id: uuid.UUID, target_status: str = "production") -> Model:
        model = await self.repository.get_by_id(model_id)
        if not model:
            raise NotFoundAppException(f"Model {model_id} not found")

        target = self._normalize_status(target_status)
        current = self._normalize_status(model.status)

        if target == current:
            return model
        if target == "candidate":
            raise BadRequestAppException("transition to candidate is not allowed")
        if current == "candidate" and target in {"production", "archived"}:
            pass
        elif current == "production" and target == "archived":
            pass
        else:
            raise BadRequestAppException(f"invalid transition: {current} -> {target}")

        if target == "production":
            rows = await self.repository.list_other_production_models(
                project_id=model.project_id,
                exclude_model_id=model.id,
            )
            for item in rows:
                await self.repository.update_or_raise(
                    item.id,
                    ModelPatch(status="archived").model_dump(exclude_none=True),
                )
            return await self.repository.update_or_raise(
                model_id,
                ModelPatch(status=target, promoted_at=datetime.now(UTC)).model_dump(exclude_none=True),
            )

        return await self.repository.update_or_raise(
            model_id,
            ModelPatch(status=target).model_dump(exclude_none=True),
        )

    async def get_by_id_or_raise(self, model_id: uuid.UUID) -> Model:
        return await self.repository.get_by_id_or_raise(model_id)

    async def get_artifact_download_url(
            self,
            *,
            model_id: uuid.UUID,
            artifact_name: str,
            expires_in_hours: int = 2,
    ) -> str:
        model = await self.get_by_id_or_raise(model_id)
        artifact = (model.artifacts or {}).get(artifact_name)
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
