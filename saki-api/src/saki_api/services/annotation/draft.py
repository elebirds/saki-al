"""
Annotation Draft Service - Business logic for Draft staging area.
"""

from loguru import logger
import uuid
from typing import Any, Dict, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.db.transaction import transactional
from saki_api.models.l2.annotation_draft import AnnotationDraft
from saki_api.repositories.annotation.draft import AnnotationDraftRepository
from saki_api.repositories.project import ProjectRepository
from saki_api.repositories.project.sample import SampleRepository
from saki_api.services.base import BaseService
from saki_api.services.project.project import ProjectService



class AnnotationDraftService(BaseService[AnnotationDraft, AnnotationDraftRepository, dict, dict]):
    """
    Service for managing annotation drafts (staging area).
    """

    def __init__(self, session: AsyncSession):
        super().__init__(AnnotationDraft, AnnotationDraftRepository, session)
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.sample_repo = SampleRepository(session)
        self.project_service = ProjectService(session)

    async def _ensure_project_sample(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> None:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        sample = await self.sample_repo.get_by_id(sample_id)
        if not sample:
            raise NotFoundAppException(f"Sample {sample_id} not found")

        dataset_ids = await self.project_repo.get_linked_dataset_ids(project_id)
        if sample.dataset_id not in dataset_ids:
            raise BadRequestAppException(
                f"Sample {sample_id} is not in any dataset linked to this project"
            )

    def _normalize_annotations(
            self,
            annotations: List[Dict[str, Any]],
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in annotations:
            item_project_id = item.get("project_id")
            item_sample_id = item.get("sample_id")
            try:
                if item_project_id and uuid.UUID(str(item_project_id)) != project_id:
                    raise BadRequestAppException("Annotation project_id mismatch")
                if item_sample_id and uuid.UUID(str(item_sample_id)) != sample_id:
                    raise BadRequestAppException("Annotation sample_id mismatch")
            except ValueError as exc:
                raise BadRequestAppException("Invalid annotation project_id/sample_id") from exc

            if not item_project_id:
                item["project_id"] = str(project_id)
            if not item_sample_id:
                item["sample_id"] = str(sample_id)
            if not item.get("annotator_id"):
                item["annotator_id"] = str(user_id)
            normalized.append(item)
        return normalized

    @transactional
    async def upsert_draft(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            payload: Dict[str, Any],
    ) -> AnnotationDraft:
        await self._ensure_project_sample(project_id, sample_id)

        annotations = payload.get("annotations") or []
        if not isinstance(annotations, list):
            raise BadRequestAppException("Draft payload must include annotations list")

        payload["annotations"] = self._normalize_annotations(
            annotations=annotations,
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
        )

        existing = await self.repository.get_by_unique(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            branch_name=branch_name,
        )
        if existing:
            updated = await self.repository.update(
                existing.id,
                {"payload": payload},
            )
            if not updated:
                raise BadRequestAppException("Failed to update draft")
            return updated

        return await self.repository.create({
            "project_id": project_id,
            "sample_id": sample_id,
            "user_id": user_id,
            "branch_name": branch_name,
            "payload": payload,
        })

    async def list_drafts(
            self,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: Optional[str] = None,
            sample_id: Optional[uuid.UUID] = None,
    ) -> List[AnnotationDraft]:
        return await self.repository.list_by_user_project(
            user_id=user_id,
            project_id=project_id,
            branch_name=branch_name,
            sample_id=sample_id,
        )

    @transactional
    async def delete_drafts(
            self,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: Optional[str] = None,
            sample_id: Optional[uuid.UUID] = None,
    ) -> int:
        return await self.repository.delete_by_user_project(
            user_id=user_id,
            project_id=project_id,
            branch_name=branch_name,
            sample_id=sample_id,
        )

    @transactional
    async def commit_from_drafts(
            self,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            commit_message: str,
            sample_ids: Optional[List[uuid.UUID]] = None,
    ):
        drafts = await self.repository.list_by_user_project(
            user_id=user_id,
            project_id=project_id,
            branch_name=branch_name,
            sample_id=None,
        )
        if sample_ids:
            sample_id_set = {sid for sid in sample_ids}
            drafts = [d for d in drafts if d.sample_id in sample_id_set]

        if not drafts:
            raise BadRequestAppException("No drafts to commit")

        annotation_changes: List[Dict[str, Any]] = []
        for draft in drafts:
            payload = draft.payload or {}
            items = payload.get("annotations") or []
            for item in items:
                # Ensure required fields
                if not item.get("project_id"):
                    item["project_id"] = str(project_id)
                if not item.get("sample_id"):
                    item["sample_id"] = str(draft.sample_id)
                if not item.get("annotator_id"):
                    item["annotator_id"] = str(user_id)
                annotation_changes.append(item)

        commit = await self.project_service.save_annotations(
            project_id=project_id,
            branch_name=branch_name,
            annotation_changes=annotation_changes,
            commit_message=commit_message,
            author_id=user_id,
            touched_sample_ids=[d.sample_id for d in drafts],
        )

        used_sample_ids = [d.sample_id for d in drafts]
        await self.repository.delete_by_user_project(
            user_id=user_id,
            project_id=project_id,
            branch_name=branch_name,
            sample_id=None,
        )

        return commit, used_sample_ids
