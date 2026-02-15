"""
Model service for L3 model registry operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.runtime.api.model import ModelCreateData, ModelPatch
from saki_api.modules.runtime.domain.model import Model
from saki_api.modules.runtime.repo.round import RoundRepository
from saki_api.modules.runtime.repo.loop import LoopRepository
from saki_api.modules.runtime.repo.model import ModelRepository


class ModelService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.round_repo = RoundRepository(session)
        self.loop_repo = LoopRepository(session)
        self.repository = ModelRepository(session)
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    @transactional
    async def register_from_round(
            self,
            *,
            project_id: uuid.UUID,
            round_id: uuid.UUID,
            created_by: uuid.UUID | None,
            name: str | None,
            version_tag: str,
            status: str,
    ) -> Model:
        round_row = await self.round_repo.get_by_id(round_id)
        if not round_row:
            raise NotFoundAppException(f"Round {round_id} not found")
        if round_row.project_id != project_id:
            raise BadRequestAppException("Round does not belong to this project")
        if not round_row.final_artifacts:
            raise BadRequestAppException("Round has no artifacts")

        loop = await self.loop_repo.get_by_id(round_row.loop_id)
        model_name = name or f"{loop.name if loop else 'loop'}-round-{round_row.round_index}"
        parent_model_id = None

        artifact_map = dict(round_row.final_artifacts or {})
        weights_path = ""
        if "best.pt" in artifact_map and isinstance(artifact_map["best.pt"], dict):
            weights_path = str(artifact_map["best.pt"].get("uri") or "")
        if not weights_path:
            for _, item in artifact_map.items():
                if isinstance(item, dict) and str(item.get("kind") or "").lower() == "weights":
                    weights_path = str(item.get("uri") or "")
                    if weights_path:
                        break
        if not weights_path:
            raise BadRequestAppException("No weights artifact found on round")

        create_data = ModelCreateData(
            project_id=project_id,
            source_commit_id=round_row.input_commit_id,
            parent_model_id=parent_model_id,
            plugin_id=round_row.plugin_id,
            model_arch=loop.model_arch if loop else round_row.plugin_id,
            name=model_name,
            version_tag=version_tag,
            weights_path=weights_path,
            status=status or "candidate",
            metrics=dict(round_row.final_metrics or {}),
            artifacts=artifact_map,
            created_by=created_by,
        )
        created = await self.repository.create(create_data.model_dump(exclude_none=True))
        return created

    async def list_by_project(self, project_id: uuid.UUID, limit: int = 100) -> list[Model]:
        return await self.repository.list_by_project(project_id=project_id, limit=limit)

    @transactional
    async def promote(self, model_id: uuid.UUID, target_status: str = "production") -> Model:
        model = await self.repository.get_by_id(model_id)
        if not model:
            raise NotFoundAppException(f"Model {model_id} not found")

        if target_status == "production":
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
                ModelPatch(status=target_status, promoted_at=datetime.now(UTC)).model_dump(exclude_none=True),
            )

        return await self.repository.update_or_raise(
            model_id,
            ModelPatch(status=target_status).model_dump(exclude_none=True),
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
        raise BadRequestAppException(f"Unsupported artifact URI: {uri}")
