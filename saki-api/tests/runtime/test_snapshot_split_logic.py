from __future__ import annotations

import uuid

import pytest

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.runtime.service.runtime_service.snapshot_mixin import SnapshotMixin
from saki_api.modules.shared.modeling.enums import SnapshotPartition, SnapshotUpdateMode, SnapshotValPolicy


def _sample_ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid5(uuid.NAMESPACE_DNS, f"sample-{idx}") for idx in range(n)]


def test_init_assignment_is_deterministic_for_same_seed() -> None:
    sample_ids = _sample_ids(64)
    rows_a = SnapshotMixin._assign_init_partitions(
        sample_ids=sample_ids,
        seed="seed-fixed",
        test_ratio=0.1,
        val_ratio=0.1,
        train_seed_ratio=0.1,
    )
    rows_b = SnapshotMixin._assign_init_partitions(
        sample_ids=sample_ids,
        seed="seed-fixed",
        test_ratio=0.1,
        val_ratio=0.1,
        train_seed_ratio=0.1,
    )
    assert rows_a == rows_b
    assert SnapshotMixin._manifest_hash(rows_a) == SnapshotMixin._manifest_hash(rows_b)


def test_append_split_anchor_only_produces_no_val_batch() -> None:
    rows = SnapshotMixin._assign_append_split_partitions(
        sample_ids=_sample_ids(50),
        seed="seed-append",
        cohort_index=3,
        test_ratio=0.2,
        val_ratio=0.3,
        val_policy=SnapshotValPolicy.ANCHOR_ONLY,
    )
    assert all(row["partition"] != SnapshotPartition.VAL_BATCH for row in rows)


def test_append_split_expand_with_batch_val_produces_val_batch() -> None:
    rows = SnapshotMixin._assign_append_split_partitions(
        sample_ids=_sample_ids(120),
        seed="seed-append",
        cohort_index=4,
        test_ratio=0.1,
        val_ratio=0.2,
        val_policy=SnapshotValPolicy.EXPAND_WITH_BATCH_VAL,
    )
    assert any(row["partition"] == SnapshotPartition.VAL_BATCH for row in rows)


def test_compute_seed_is_reproducible_without_requested_seed() -> None:
    mixin = SnapshotMixin()
    loop_id = uuid.uuid4()
    seed_v1_a = mixin._compute_seed(loop_id=loop_id, version_index=1, requested_seed=None)
    seed_v1_b = mixin._compute_seed(loop_id=loop_id, version_index=1, requested_seed=None)
    seed_v2 = mixin._compute_seed(loop_id=loop_id, version_index=2, requested_seed=None)
    explicit = mixin._compute_seed(loop_id=loop_id, version_index=2, requested_seed="user-seed")
    assert seed_v1_a == seed_v1_b
    assert seed_v1_a != seed_v2
    assert explicit == "user-seed"


def test_parse_enum_accepts_enum_value_name_and_qualified_name() -> None:
    mixin = SnapshotMixin()
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
    mixin = SnapshotMixin()
    with pytest.raises(BadRequestAppException):
        mixin._parse_enum(SnapshotValPolicy, "not-valid", field_name="val_policy")


@pytest.mark.anyio
async def test_count_labeled_samples_only_uses_review_state() -> None:
    sample_a = uuid.uuid4()
    sample_b = uuid.uuid4()
    sample_c = uuid.uuid4()

    class _Result:
        def __init__(self, rows: list[uuid.UUID]):
            self._rows = rows

        def all(self) -> list[uuid.UUID]:
            return list(self._rows)

    class _Session:
        def __init__(self) -> None:
            self.calls = 0

        async def exec(self, _stmt):  # noqa: ANN001
            self.calls += 1
            # Reviewed set from CommitSampleState (includes EMPTY_CONFIRMED/LABELED).
            return _Result([sample_a])

    mixin = SnapshotMixin()
    mixin.session = _Session()  # type: ignore[attr-defined]
    labeled = await mixin._count_labeled_samples(
        commit_id=uuid.uuid4(),
        sample_ids=[sample_a, sample_b, sample_c],
    )
    assert labeled == {sample_a}
    assert mixin.session.calls == 1
