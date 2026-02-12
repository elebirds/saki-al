"""
Commit hash utilities.

Provides stable commit hash generation based on:
- parent commit hash
- commit metadata
- normalized annotation snapshot at this commit
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.annotation.annotation import Annotation
from saki_api.models.annotation.camap import CommitAnnotationMap
from saki_api.models.project.commit_sample_state import CommitSampleState
from saki_api.models.project.commit import Commit
from saki_api.models.project.label import Label


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def build_snapshot_signature(session: AsyncSession, commit_id: uuid.UUID) -> str:
    rows = await session.exec(
        select(
            CommitAnnotationMap.sample_id,
            Annotation.lineage_id,
            Annotation.group_id,
            Annotation.view_role,
            Annotation.type,
            Annotation.source,
            Annotation.confidence,
            Annotation.data,
            Label.name,
        )
        .join(Annotation, Annotation.id == CommitAnnotationMap.annotation_id)
        .join(Label, Label.id == Annotation.label_id)
        .where(CommitAnnotationMap.commit_id == commit_id)
    )

    snapshot_items: list[dict[str, Any]] = []
    for row in rows.all():
        (
            sample_id,
            lineage_id,
            group_id,
            view_role,
            ann_type,
            ann_source,
            confidence,
            ann_data,
            label_name,
        ) = row
        snapshot_items.append(
            {
                "sample_id": str(sample_id),
                "lineage_id": str(lineage_id),
                "group_id": str(group_id),
                "view_role": str(view_role),
                "type": str(ann_type),
                "source": str(ann_source),
                "confidence": float(confidence),
                "label_name": str(label_name),
                "data": ann_data or {},
            }
        )

    snapshot_items.sort(
        key=lambda item: (
            item["sample_id"],
            item["lineage_id"],
            item["group_id"],
            item["view_role"],
            item["type"],
            item["label_name"],
            item["source"],
            _canonical_json(item["data"]),
            item["confidence"],
        )
    )

    sample_state_rows = await session.exec(
        select(
            CommitSampleState.sample_id,
            CommitSampleState.state,
        ).where(CommitSampleState.commit_id == commit_id)
    )
    sample_states = [
        {
            "sample_id": str(sample_id),
            "state": str(state),
        }
        for sample_id, state in sample_state_rows.all()
    ]
    sample_states.sort(key=lambda item: (item["sample_id"], item["state"]))

    return _sha256_text(_canonical_json({
        "annotations": snapshot_items,
        "sample_states": sample_states,
    }))


async def calculate_commit_hash(session: AsyncSession, commit: Commit) -> str:
    parent_hash = ""
    if commit.parent_id:
        parent = await session.get(Commit, commit.parent_id)
        parent_hash = str(parent.commit_hash or "") if parent else ""

    snapshot_signature = await build_snapshot_signature(session, commit.id)
    payload = {
        "parent_commit_hash": parent_hash,
        "message": str(commit.message or ""),
        "author_type": str(commit.author_type or ""),
        "author_id": str(commit.author_id) if commit.author_id else "",
        "created_at": commit.created_at.isoformat() if commit.created_at else "",
        "snapshot_signature": snapshot_signature,
    }
    return _sha256_text(_canonical_json(payload))


async def refresh_commit_hash(session: AsyncSession, commit: Commit) -> str:
    commit_hash = await calculate_commit_hash(session, commit)
    commit.commit_hash = commit_hash
    session.add(commit)
    await session.flush()
    return commit_hash
