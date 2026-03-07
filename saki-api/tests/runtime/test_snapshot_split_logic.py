from __future__ import annotations

import uuid

import pytest

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.runtime.service.runtime_service.round_reveal_mixin import RoundRevealMixin
from saki_api.modules.runtime.service.runtime_service.snapshot_policy_mixin import SnapshotPolicyMixin
from saki_api.modules.shared.modeling.enums import SnapshotPartition, SnapshotUpdateMode, SnapshotValPolicy


def _sample_ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid5(uuid.NAMESPACE_DNS, f"sample-{idx}") for idx in range(n)]


def test_init_assignment_is_deterministic_for_same_seed() -> None:
    sample_ids = _sample_ids(64)
    rows_a = SnapshotPolicyMixin._assign_init_partitions(
        sample_ids=sample_ids,
        seed="seed-fixed",
        test_ratio=0.1,
        val_ratio=0.1,
        train_seed_ratio=0.1,
    )
    rows_b = SnapshotPolicyMixin._assign_init_partitions(
        sample_ids=sample_ids,
        seed="seed-fixed",
        test_ratio=0.1,
        val_ratio=0.1,
        train_seed_ratio=0.1,
    )
    assert rows_a == rows_b
    assert SnapshotPolicyMixin._manifest_hash(rows_a) == SnapshotPolicyMixin._manifest_hash(rows_b)


def test_append_split_anchor_only_produces_no_val_batch() -> None:
    rows = SnapshotPolicyMixin._assign_append_split_partitions(
        sample_ids=_sample_ids(50),
        seed="seed-append",
        cohort_index=3,
        test_ratio=0.2,
        val_ratio=0.3,
        val_policy=SnapshotValPolicy.ANCHOR_ONLY,
    )
    assert all(row["partition"] != SnapshotPartition.VAL_BATCH for row in rows)


def test_append_split_expand_with_batch_val_produces_val_batch() -> None:
    rows = SnapshotPolicyMixin._assign_append_split_partitions(
        sample_ids=_sample_ids(120),
        seed="seed-append",
        cohort_index=4,
        test_ratio=0.1,
        val_ratio=0.2,
        val_policy=SnapshotValPolicy.EXPAND_WITH_BATCH_VAL,
    )
    assert any(row["partition"] == SnapshotPartition.VAL_BATCH for row in rows)


def test_resolve_snapshot_seed_uses_loop_global_seed() -> None:
    class _SeedMixin(SnapshotPolicyMixin):
        _get_loop_global_seed = staticmethod(
            lambda raw_config: str((raw_config.get("reproducibility") or {}).get("global_seed") or "").strip()
        )

    mixin = _SeedMixin()
    loop = type("LoopStub", (), {"config": {"reproducibility": {"global_seed": "seed-loop-main"}}})()
    assert mixin._resolve_snapshot_seed(loop=loop) == "seed-loop-main"
    missing_seed_loop = type("LoopStub", (), {"config": {"reproducibility": {}}})()
    with pytest.raises(BadRequestAppException, match="global_seed"):
        mixin._resolve_snapshot_seed(loop=missing_seed_loop)


def test_parse_enum_accepts_enum_value_name_and_qualified_name() -> None:
    mixin = SnapshotPolicyMixin()
    assert (
        mixin._parse_enum(
            SnapshotValPolicy,
            SnapshotValPolicy.EXPAND_WITH_BATCH_VAL,
            field_name="val_policy",
        )
        == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL
    )
    assert (
        mixin._parse_enum(
            SnapshotValPolicy,
            "expand_with_batch_val",
            field_name="val_policy",
        )
        == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL
    )
    assert (
        mixin._parse_enum(
            SnapshotValPolicy,
            "EXPAND_WITH_BATCH_VAL",
            field_name="val_policy",
        )
        == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL
    )
    assert (
        mixin._parse_enum(
            SnapshotValPolicy,
            "SnapshotValPolicy.EXPAND_WITH_BATCH_VAL",
            field_name="val_policy",
        )
        == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL
    )
    assert (
        mixin._parse_enum(
            SnapshotUpdateMode,
            "SnapshotUpdateMode.APPEND_SPLIT",
            field_name="mode",
        )
        == SnapshotUpdateMode.APPEND_SPLIT
    )


def test_parse_enum_rejects_invalid_value() -> None:
    mixin = SnapshotPolicyMixin()
    with pytest.raises(BadRequestAppException):
        mixin._parse_enum(SnapshotValPolicy, "not-valid", field_name="val_policy")


@pytest.mark.anyio
async def test_count_labeled_samples_only_uses_review_state() -> None:
    sample_a = uuid.uuid4()
    sample_b = uuid.uuid4()
    sample_c = uuid.uuid4()

    class _Gateway:
        def __init__(self) -> None:
            self.calls = 0

        async def list_labeled_sample_ids_at_commit(self, *, commit_id, sample_ids):  # noqa: ANN001
            self.calls += 1
            assert commit_id is not None
            assert sample_ids
            return [sample_a]

    mixin = RoundRevealMixin()
    mixin.annotation_gateway = _Gateway()  # type: ignore[attr-defined]
    labeled = await mixin._count_labeled_samples(
        commit_id=uuid.uuid4(),
        sample_ids=[sample_a, sample_b, sample_c],
    )
    assert labeled == {sample_a}
    assert mixin.annotation_gateway.calls == 1
