"""
Annotation Draft Service - Business logic for Draft staging area.
"""

import uuid
from typing import Any, Dict, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.annotation.repo.draft import AnnotationDraftRepository
from saki_api.modules.annotation.service.working import AnnotationWorkingService
from saki_api.modules.project.contracts import ProjectReadGateway
from saki_api.modules.project.service.project import ProjectService
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class AnnotationDraftService(CrudServiceBase[AnnotationDraft, AnnotationDraftRepository, dict, dict]):
    """
    Service for managing annotation drafts (staging area).
    """

    def __init__(self, session: AsyncSession):
        super().__init__(AnnotationDraft, AnnotationDraftRepository, session)
        self.session = session
        self.project_gateway = ProjectReadGateway(session)
        self.project_service = ProjectService(session)
        self.working_service = AnnotationWorkingService()

    _BATCH_STATUS_VALUES = {"all", "labeled", "unlabeled", "draft"}
    _BATCH_SORT_ORDER_VALUES = {"asc", "desc"}
    _BATCH_OPERATION_VALUES = {
        "clear_drafts",
        "confirm_model_annotations",
        "clear_unconfirmed_model_annotations",
    }

    @staticmethod
    def _list_annotation_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        annotations = payload.get("annotations")
        if not isinstance(annotations, list):
            return []
        return [dict(item) for item in annotations if isinstance(item, dict)]

    @staticmethod
    def _resolve_group_id(item: Dict[str, Any]) -> str:
        return str(
            item.get("group_id")
            or item.get("groupId")
            or item.get("id")
            or ""
        ).strip()

    @staticmethod
    def _normalize_source(item: Dict[str, Any]) -> str:
        return str(item.get("source") or "").strip().lower()

    async def _ensure_project_sample(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> None:
        project = await self.project_gateway.get_project(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        sample = await self.project_gateway.get_sample(sample_id)
        if not sample:
            raise NotFoundAppException(f"Sample {sample_id} not found")

        dataset_ids = await self.project_gateway.get_linked_dataset_ids(project_id)
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
        touched_sample_ids: List[uuid.UUID] = []
        touched_sample_id_set: set[uuid.UUID] = set()
        committed_draft_sample_ids: set[uuid.UUID] = set()
        for draft in drafts:
            payload = draft.payload or {}
            items = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            reviewed_empty = bool(meta.get("reviewed_empty"))

            unconfirmed_group_ids: set[str] = set()
            for item in items:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("source") or "").strip().lower()
                if source != "model":
                    continue
                group_id = str(item.get("group_id") or item.get("groupId") or item.get("id") or "").strip()
                if group_id:
                    unconfirmed_group_ids.add(group_id)

            committable_items: List[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("source") or "").strip().lower()
                group_id = str(item.get("group_id") or item.get("groupId") or item.get("id") or "").strip()
                if source == "model":
                    continue
                if group_id and group_id in unconfirmed_group_ids:
                    continue
                committable_items.append(item)

            if not committable_items and not reviewed_empty:
                continue

            if draft.sample_id not in touched_sample_id_set:
                touched_sample_id_set.add(draft.sample_id)
                touched_sample_ids.append(draft.sample_id)
            committed_draft_sample_ids.add(draft.sample_id)

            for item in committable_items:
                # Ensure required fields
                if not item.get("project_id"):
                    item["project_id"] = str(project_id)
                if not item.get("sample_id"):
                    item["sample_id"] = str(draft.sample_id)
                if not item.get("annotator_id"):
                    item["annotator_id"] = str(user_id)
                annotation_changes.append(item)

        if not touched_sample_ids:
            raise BadRequestAppException("No committable drafts: please confirm model annotations first")

        commit = await self.project_service.save_annotations(
            project_id=project_id,
            branch_name=branch_name,
            annotation_changes=annotation_changes,
            commit_message=commit_message,
            author_id=user_id,
            touched_sample_ids=touched_sample_ids,
        )

        used_sample_ids = list(touched_sample_ids)
        for sample_id in committed_draft_sample_ids:
            await self.repository.delete_by_user_project(
                user_id=user_id,
                project_id=project_id,
                branch_name=branch_name,
                sample_id=sample_id,
            )

        return commit, used_sample_ids

    @transactional
    async def batch_operate_drafts(
            self,
            *,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            dataset_id: uuid.UUID,
            q: Optional[str],
            status: str,
            sort_by: str,
            sort_order: str,
            operation: str,
            dry_run: bool,
    ) -> Dict[str, Any]:
        if status not in self._BATCH_STATUS_VALUES:
            raise BadRequestAppException("Invalid status filter")
        if sort_order not in self._BATCH_SORT_ORDER_VALUES:
            raise BadRequestAppException("Invalid sort order")
        if operation not in self._BATCH_OPERATION_VALUES:
            raise BadRequestAppException("Invalid draft batch operation")

        sample_ids = await self.project_service.list_project_sample_ids_by_filter(
            project_id=project_id,
            dataset_id=dataset_id,
            current_user_id=user_id,
            branch_name=branch_name,
            q=q,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        matched_sample_count = len(sample_ids)
        if matched_sample_count == 0:
            return {
                "operation": operation,
                "dry_run": dry_run,
                "branch_name": branch_name,
                "matched_sample_count": 0,
                "matched_draft_count": 0,
                "affected_draft_count": 0,
                "affected_annotation_count": 0,
                "updated_draft_count": 0,
                "deleted_draft_count": 0,
                "cleared_working_count": 0,
            }

        drafts = await self.repository.list_by_scope_and_samples(
            project_id=project_id,
            user_id=user_id,
            branch_name=branch_name,
            sample_ids=sample_ids,
        )

        matched_draft_count = len(drafts)
        affected_draft_count = 0
        affected_annotation_count = 0
        updated_draft_count = 0
        deleted_draft_count = 0
        cleared_working_count = 0

        if operation == "clear_drafts":
            affected_draft_count = matched_draft_count
            for draft in drafts:
                payload = dict(draft.payload or {}) if isinstance(draft.payload, dict) else {}
                affected_annotation_count += len(self._list_annotation_items(payload))

            if not dry_run:
                unique_sample_ids: set[uuid.UUID] = set()
                for draft in drafts:
                    unique_sample_ids.add(draft.sample_id)
                    await self.session.delete(draft)
                    deleted_draft_count += 1
                await self.session.flush()

                for sample_id in unique_sample_ids:
                    await self.working_service.delete_working(
                        project_id=project_id,
                        sample_id=sample_id,
                        user_id=user_id,
                        branch_name=branch_name,
                    )
                    cleared_working_count += 1
        else:
            for draft in drafts:
                payload = dict(draft.payload or {}) if isinstance(draft.payload, dict) else {}
                items = self._list_annotation_items(payload)
                if not items:
                    continue

                next_items: List[Dict[str, Any]] = []
                changed_count = 0

                if operation == "confirm_model_annotations":
                    for item in items:
                        if self._normalize_source(item) == "model":
                            next_item = {**item, "source": "confirmed_model"}
                            changed_count += 1
                        else:
                            next_item = item
                        next_items.append(next_item)

                if operation == "clear_unconfirmed_model_annotations":
                    model_group_ids: set[str] = set()
                    for item in items:
                        if self._normalize_source(item) != "model":
                            continue
                        group_id = self._resolve_group_id(item)
                        if group_id:
                            model_group_ids.add(group_id)

                    for item in items:
                        source = self._normalize_source(item)
                        group_id = self._resolve_group_id(item)
                        should_remove = source == "model" or (group_id and group_id in model_group_ids)
                        if should_remove:
                            changed_count += 1
                            continue
                        next_items.append(item)

                if changed_count <= 0:
                    continue

                affected_draft_count += 1
                affected_annotation_count += changed_count

                if not dry_run:
                    next_payload = {**payload, "annotations": next_items}
                    await self.repository.update(draft.id, {"payload": next_payload})
                    updated_draft_count += 1

        return {
            "operation": operation,
            "dry_run": dry_run,
            "branch_name": branch_name,
            "matched_sample_count": matched_sample_count,
            "matched_draft_count": matched_draft_count,
            "affected_draft_count": affected_draft_count,
            "affected_annotation_count": affected_annotation_count,
            "updated_draft_count": updated_draft_count,
            "deleted_draft_count": deleted_draft_count,
            "cleared_working_count": cleared_working_count,
        }
