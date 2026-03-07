from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.project.service.project import ProjectService


class AnnotationBulkService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.project_service = ProjectService(session)

    async def save_annotations(
        self,
        *,
        project_id: uuid.UUID,
        branch_name: str,
        commit_message: str,
        annotation_changes: list[dict[str, Any]],
        author_id: uuid.UUID,
        touched_sample_ids: list[uuid.UUID] | None = None,
    ):
        return await self.project_service.save_annotations(
            project_id=project_id,
            branch_name=branch_name,
            annotation_changes=annotation_changes,
            commit_message=commit_message,
            author_id=author_id,
            touched_sample_ids=touched_sample_ids,
        )

    async def iter_bulk_save_annotations(
        self,
        *,
        project_id: uuid.UUID,
        branch_name: str,
        commit_message: str,
        annotation_changes: list[dict[str, Any]],
        author_id: uuid.UUID,
    ) -> AsyncIterator[dict[str, Any]]:
        total = len(annotation_changes)
        yield {
            "event": "start",
            "phase": "annotation_bulk_execute",
            "message": "annotation bulk save started",
            "current": 0,
            "total": total,
        }
        try:
            commit = await self.save_annotations(
                project_id=project_id,
                branch_name=branch_name,
                commit_message=commit_message,
                annotation_changes=annotation_changes,
                author_id=author_id,
            )
            yield {
                "event": "phase",
                "phase": "annotation_bulk_execute",
                "message": f"saved {total} annotations",
                "current": total,
                "total": total,
            }
            yield {
                "event": "complete",
                "message": "annotation bulk save completed",
                "detail": {
                    "project_id": str(project_id),
                    "branch_name": branch_name,
                    "commit_id": str(commit.id),
                    "saved_annotations": total,
                    "stats": dict(commit.stats or {}),
                },
            }
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "error",
                "phase": "annotation_bulk_execute",
                "message": str(exc),
                "detail": {"code": "ANNOTATION_BULK_SAVE_FAILED"},
            }
            yield {
                "event": "complete",
                "message": "annotation bulk save failed",
                "detail": {
                    "failed": True,
                    "error": str(exc),
                    "code": "ANNOTATION_BULK_SAVE_FAILED",
                },
            }
