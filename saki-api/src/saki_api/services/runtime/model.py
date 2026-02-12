"""
Model service for L3 model registry operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.models.runtime.job import Job
from saki_api.models.runtime.loop import ALLoop
from saki_api.models.runtime.model import Model
from saki_api.utils.storage import get_storage_provider


class ModelService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    async def register_from_job(
            self,
            *,
            project_id: uuid.UUID,
            job_id: uuid.UUID,
            created_by: uuid.UUID | None,
            name: str | None,
            version_tag: str,
            status: str,
    ) -> Model:
        job = await self.session.get(Job, job_id)
        if not job:
            raise NotFoundAppException(f"Job {job_id} not found")
        if job.project_id != project_id:
            raise BadRequestAppException("Job does not belong to this project")
        if not job.final_artifacts:
            raise BadRequestAppException("Job has no artifacts")

        loop = await self.session.get(ALLoop, job.loop_id)
        model_name = name or f"{loop.name if loop else 'loop'}-round-{job.round_index}"
        parent_model_id = loop.latest_model_id if loop else None

        artifact_map = dict(job.final_artifacts or {})
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
            raise BadRequestAppException("No weights artifact found on job")

        model = Model(
            project_id=project_id,
            job_id=job.id,
            source_commit_id=job.source_commit_id,
            parent_model_id=parent_model_id,
            plugin_id=job.plugin_id,
            model_arch=loop.model_arch if loop else job.plugin_id,
            name=model_name,
            version_tag=version_tag,
            weights_path=weights_path,
            status=status or "candidate",
            metrics=dict(job.final_metrics or {}),
            artifacts=artifact_map,
            created_by=created_by,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)

        job.model_id = model.id
        self.session.add(job)
        if loop:
            loop.latest_model_id = model.id
            self.session.add(loop)

        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def list_by_project(self, project_id: uuid.UUID, limit: int = 100) -> list[Model]:
        rows = await self.session.exec(
            select(Model)
            .where(Model.project_id == project_id)
            .order_by(Model.created_at.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def promote(self, model_id: uuid.UUID, target_status: str = "production") -> Model:
        model = await self.session.get(Model, model_id)
        if not model:
            raise NotFoundAppException(f"Model {model_id} not found")

        if target_status == "production":
            rows = await self.session.exec(
                select(Model).where(
                    Model.project_id == model.project_id,
                    Model.status == "production",
                    Model.id != model.id,
                )
            )
            for item in rows.all():
                item.status = "archived"
                self.session.add(item)
            model.promoted_at = datetime.now(UTC)

        model.status = target_status
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def get_by_id_or_raise(self, model_id: uuid.UUID) -> Model:
        model = await self.session.get(Model, model_id)
        if not model:
            raise NotFoundAppException(f"Model {model_id} not found")
        return model

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
