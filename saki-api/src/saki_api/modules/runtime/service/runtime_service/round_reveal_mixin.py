"""Round reveal and missing-sample mixin."""

from __future__ import annotations

import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.service.runtime_service.snapshot_policy_mixin import _RevealProbe
from saki_api.modules.shared.modeling.enums import (
    CommitSampleReviewState,
    VisibilitySource,
)


class RoundRevealMixin:
    async def _count_labeled_samples(
        self,
        *,
        commit_id: uuid.UUID,
        sample_ids: list[uuid.UUID],
    ) -> set[uuid.UUID]:
        if not sample_ids:
            return set()
        labeled_ids = await self.annotation_gateway.list_labeled_sample_ids_at_commit(
            commit_id=commit_id,
            sample_ids=list(set(sample_ids)),
        )
        return set(labeled_ids)

    async def _load_selected_sample_ids(
        self,
        *,
        round_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        return await self.step_candidate_repo.list_selected_sample_ids_by_round(round_id)

    async def _probe_round_reveal(
        self,
        *,
        loop_id: uuid.UUID,
        round_id: uuid.UUID,
        loop: Any | None = None,
    ) -> _RevealProbe:
        loop_row = loop if loop is not None else await self.loop_repo.get_by_id_or_raise(loop_id)
        latest_commit_id = await self._resolve_reveal_source_commit_id(loop=loop_row)
        selected_sample_ids = await self._load_selected_sample_ids(round_id=round_id)
        if not selected_sample_ids:
            return _RevealProbe(
                selected_count=0,
                revealable_count=0,
                missing_count=0,
                missing_sample_ids=[],
                revealable_sample_ids=[],
                latest_commit_id=latest_commit_id,
            )
        if not latest_commit_id:
            return _RevealProbe(
                selected_count=len(selected_sample_ids),
                revealable_count=0,
                missing_count=len(selected_sample_ids),
                missing_sample_ids=list(selected_sample_ids),
                revealable_sample_ids=[],
                latest_commit_id=None,
            )
        labeled_ids = await self.snapshot_query_repo.list_labeled_sample_ids(
            commit_id=latest_commit_id,
            sample_ids=selected_sample_ids,
        )
        visible_ids = await self.snapshot_query_repo.list_visible_sample_ids(
            loop_id=loop_id,
            sample_ids=selected_sample_ids,
        )
        revealable = [sample_id for sample_id in selected_sample_ids if sample_id in labeled_ids and sample_id not in visible_ids]
        missing = [sample_id for sample_id in selected_sample_ids if sample_id not in labeled_ids]
        return _RevealProbe(
            selected_count=len(selected_sample_ids),
            revealable_count=len(revealable),
            missing_count=len(missing),
            missing_sample_ids=missing,
            revealable_sample_ids=revealable,
            latest_commit_id=latest_commit_id,
        )

    @staticmethod
    def _build_wait_user_gate_meta(
        *,
        loop_id: uuid.UUID,
        round_row: Round,
        selected_count: int,
        revealed_count: int,
        missing_count: int,
        min_required: int,
        configured_min_required: int,
    ) -> dict[str, Any]:
        return {
            "round_id": str(round_row.id),
            "round_index": int(round_row.round_index or 0),
            "selected_count": int(selected_count),
            "revealed_count": int(revealed_count),
            "missing_count": int(missing_count),
            "min_required": int(min_required),
            "configured_min_required": int(configured_min_required),
            "annotation_scope": {
                "type": "round_missing_labels",
                "loop_id": str(loop_id),
                "round_id": str(round_row.id),
            },
        }

    async def list_round_missing_samples(
        self,
        *,
        loop_id: uuid.UUID,
        round_id: uuid.UUID,
        current_user_id: uuid.UUID,
        dataset_id: uuid.UUID | None = None,
        q: str | None = None,
        sort_by: str = "createdAt",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 24,
    ) -> dict[str, Any]:
        loop = await self.loop_repo.get_by_id_or_raise(loop_id)
        round_row = await self.repository.get_by_id_or_raise(round_id)
        if round_row.loop_id != loop_id:
            raise BadRequestAppException("round_id does not belong to loop")

        probe = await self._probe_round_reveal(loop_id=loop_id, round_id=round_id, loop=loop)
        configured_min_required = max(1, int(loop.min_new_labels_per_round or 1))
        effective_min_required = self._effective_round_min_required(
            selected_count=probe.selected_count,
            configured_min_required=configured_min_required,
        )

        missing_ids = list(probe.missing_sample_ids or [])
        if not missing_ids:
            return {
                **self._build_wait_user_gate_meta(
                    loop_id=loop_id,
                    round_row=round_row,
                    selected_count=probe.selected_count,
                    revealed_count=probe.revealable_count,
                    missing_count=probe.missing_count,
                    min_required=effective_min_required,
                    configured_min_required=configured_min_required,
                ),
                "loop_id": loop_id,
                "round_id": round_row.id,
                "dataset_stats": [],
                "items": [],
                "total": 0,
                "offset": 0,
                "limit": int(max(1, min(int(limit or 24), 200))),
                "size": 0,
                "has_more": False,
            }

        dataset_stats = await self.snapshot_query_repo.list_dataset_stats_for_samples(sample_ids=missing_ids)
        dataset_stats.sort(key=lambda item: (-int(item["count"]), str(item["dataset_id"])))

        safe_limit = int(max(1, min(int(limit or 24), 200)))
        safe_page = int(max(1, int(page or 1)))
        offset = (safe_page - 1) * safe_limit
        total = await self.snapshot_query_repo.count_samples(
            sample_ids=missing_ids,
            dataset_id=dataset_id,
            q=q,
        )
        samples = await self.snapshot_query_repo.list_samples_page(
            sample_ids=missing_ids,
            dataset_id=dataset_id,
            q=q,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=safe_limit,
        )

        sample_ids = [sample.id for sample in samples]
        annotation_counts: dict[uuid.UUID, int] = {}
        review_states: dict[uuid.UUID, CommitSampleReviewState] = {}
        if sample_ids and probe.latest_commit_id:
            annotation_counts = await self.annotation_gateway.count_annotations_by_sample_at_commit(
                commit_id=probe.latest_commit_id,
                sample_ids=sample_ids,
            )
            review_states = await self.annotation_gateway.list_review_states_at_commit(
                commit_id=probe.latest_commit_id,
                sample_ids=sample_ids,
            )

        branch_name = (await self.project_gateway.get_branch_name(loop.branch_id)) or "master"

        draft_ids: set[uuid.UUID] = set()
        if sample_ids:
            draft_ids = set(
                await self.annotation_gateway.list_draft_sample_ids(
                    project_id=loop.project_id,
                    user_id=current_user_id,
                    branch_name=branch_name,
                    sample_ids=sample_ids,
                )
            )

        items: list[dict[str, Any]] = []
        for sample in samples:
            review_state = review_states.get(sample.id)
            items.append(
                {
                    "id": sample.id,
                    "dataset_id": sample.dataset_id,
                    "name": sample.name,
                    "asset_group": sample.asset_group or {},
                    "primary_asset_id": sample.primary_asset_id,
                    "remark": sample.remark,
                    "meta_info": sample.meta_info or {},
                    "created_at": sample.created_at,
                    "updated_at": sample.updated_at,
                    "annotation_count": int(annotation_counts.get(sample.id, 0)),
                    "is_labeled": review_state is not None,
                    "review_state": review_state.value if review_state else "unreviewed",
                    "has_draft": sample.id in draft_ids,
                }
            )

        size = len(items)
        return {
            **self._build_wait_user_gate_meta(
                loop_id=loop_id,
                round_row=round_row,
                selected_count=probe.selected_count,
                revealed_count=probe.revealable_count,
                missing_count=probe.missing_count,
                min_required=effective_min_required,
                configured_min_required=configured_min_required,
            ),
            "loop_id": loop_id,
            "round_id": round_row.id,
            "dataset_stats": dataset_stats,
            "items": items,
            "total": total,
            "offset": offset,
            "limit": safe_limit,
            "size": size,
            "has_more": bool(offset + size < total),
        }

    @transactional
    async def resolve_round_reveal(
        self,
        *,
        loop_id: uuid.UUID,
        round_id: uuid.UUID,
        branch_id: uuid.UUID | None = None,
        force: bool = False,
        min_required: int = 1,
    ) -> dict[str, Any]:
        loop, snapshot = await self._get_active_snapshot_or_raise(loop_id)
        if branch_id and branch_id != loop.branch_id:
            raise BadRequestAppException("branch_id does not match loop")
        round_row = await self.repository.get_by_id_or_raise(round_id)
        if round_row.loop_id != loop_id:
            raise BadRequestAppException("round_id does not belong to loop")

        snapshot_rows = await self.al_snapshot_sample_repo.list_by_snapshot(snapshot.id)
        visible_sample_ids_before = set(await self.al_loop_visibility_repo.list_visible_sample_ids(loop_id))
        train_stats_before = self._compute_snapshot_train_stats(
            rows=snapshot_rows,
            visible_sample_ids=visible_sample_ids_before,
        )

        probe = await self._probe_round_reveal(loop_id=loop_id, round_id=round_row.id, loop=loop)
        threshold = self._effective_round_min_required(
            selected_count=probe.selected_count,
            configured_min_required=int(min_required or 1),
        )
        if not force and probe.revealable_count < threshold:
            raise BadRequestAppException(
                f"not enough revealable samples: {probe.revealable_count} < {threshold}"
            )

        revealed_ids = probe.revealable_sample_ids
        visible_sample_ids_after = set(visible_sample_ids_before)
        if revealed_ids:
            source = VisibilitySource.FORCE_REVEAL if force else VisibilitySource.ROUND_REVEAL
            rows = [
                self.al_loop_visibility_repo.build_row(
                    loop_id=loop_id,
                    sample_id=sample_id,
                    visible_in_train=True,
                    source=source,
                    revealed_round_index=int(round_row.round_index),
                    reveal_commit_id=probe.latest_commit_id,
                )
                for sample_id in revealed_ids
            ]
            await self.al_loop_visibility_repo.upsert_rows(rows)
            visible_sample_ids_after.update(revealed_ids)

        train_stats_after = self._compute_snapshot_train_stats(
            rows=snapshot_rows,
            visible_sample_ids=visible_sample_ids_after,
        )

        return {
            "loop_id": loop_id,
            "round_id": round_row.id,
            "round_index": int(round_row.round_index),
            "revealed_count": len(revealed_ids),
            "selected_count": int(probe.selected_count),
            "missing_count": int(probe.missing_count),
            "effective_min_required": int(threshold),
            "latest_commit_id": probe.latest_commit_id,
            "revealable_sample_ids_hash": self._hash_sample_ids(revealed_ids),
            "pool_hidden_before": int(train_stats_before.pool_hidden),
            "pool_hidden_after": int(train_stats_after.pool_hidden),
            "train_visible_after": int(train_stats_after.train_visible),
            "total_train_universe": int(train_stats_after.total_train_universe),
        }
