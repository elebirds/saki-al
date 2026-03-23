from __future__ import annotations

from pathlib import Path

import pytest


def test_scan_dota_export_builds_expected_sample_fields(tiny_dota_export) -> None:
    from obb_baseline.splitters import scan_dota_export

    records = scan_dota_export(
        tiny_dota_export,
        class_names=("pattern_a", "pattern_b", "pattern_c"),
    )
    assert records[0].sample_id == records[0].stem
    record_map = {record.stem: record for record in records}
    sample_001 = record_map["sample_001"]
    assert sample_001.instance_count == 0
    assert sample_001.is_negative is True
    assert sample_001.class_mask == "000"
    assert sample_001.instance_count_bucket == "0"
    sample_002 = record_map["sample_002"]
    assert sample_002.instance_count == 1
    assert sample_002.is_negative is False
    assert sample_002.class_mask == "100"
    assert sample_002.instance_count_bucket == "1"
    sample_005 = record_map["sample_005"]
    assert sample_005.instance_count == 5
    assert sample_005.class_mask == "001"
    assert sample_005.instance_count_bucket == ">=5"


def test_resolve_fallback_level_downgrades_small_strata(
    sample_inventory_with_small_bucket,
) -> None:
    from obb_baseline.splitters import resolve_fallback_level

    strict_counts = {"neg|111|>=5": 1}
    class_counts = {"neg|111": 2}
    neg_counts = {"neg": 10}
    level = resolve_fallback_level(
        strict_key="neg|111|>=5",
        class_key="neg|111",
        neg_key="neg",
        strict_counts=strict_counts,
        class_counts=class_counts,
        neg_counts=neg_counts,
    )
    assert level == 2


def test_generate_split_bundle_keeps_test_fixed_when_split_seed_changes(
    sample_inventory,
) -> None:
    from obb_baseline.splitters import generate_split_bundle

    bundle = generate_split_bundle(
        sample_inventory,
        dataset_name="tiny_dota_export",
        holdout_seed=3407,
        split_seeds=[11, 17],
        test_ratio=0.15,
        val_ratio=0.15,
    )
    split_11 = bundle.manifest["splits"]["11"]
    split_17 = bundle.manifest["splits"]["17"]
    assert split_11["test_ids"] == split_17["test_ids"]


def test_generate_split_bundle_converts_val_ratio_within_trainval(
    sample_inventory,
) -> None:
    from obb_baseline.splitters import generate_split_bundle

    bundle = generate_split_bundle(
        sample_inventory,
        dataset_name="tiny_dota_export",
        holdout_seed=3407,
        split_seeds=[11],
        test_ratio=0.15,
        val_ratio=0.15,
    )
    split_11 = bundle.manifest["splits"]["11"]
    train_count = len(split_11["train_ids"])
    val_count = len(split_11["val_ids"])
    assert val_count == round((train_count + val_count) * (0.15 / 0.85))


def test_generate_split_bundle_writes_manifest_and_summary_schema(
    sample_inventory,
) -> None:
    from obb_baseline.splitters import generate_split_bundle

    bundle = generate_split_bundle(
        sample_inventory,
        dataset_name="tiny_dota_export",
        holdout_seed=3407,
        split_seeds=[11, 17, 23],
        test_ratio=0.15,
        val_ratio=0.15,
    )
    assert bundle.manifest["dataset_name"] == "tiny_dota_export"
    assert bundle.manifest["holdout_seed"] == 3407
    assert bundle.manifest["split_seeds"] == [11, 17, 23]
    assert set(bundle.manifest["splits"]["11"]) == {"train_ids", "val_ids", "test_ids"}
    assert "class_mask_distribution" in bundle.summary["splits"]["11"]
    assert "instance_count_bucket_distribution" in bundle.summary["splits"]["11"]
    assert "positive_ratio" in bundle.summary["splits"]["11"]


def test_generate_split_bundle_partitions_full_inventory(sample_inventory) -> None:
    from obb_baseline.splitters import generate_split_bundle

    bundle = generate_split_bundle(
        sample_inventory,
        dataset_name="tiny_dota_export",
        holdout_seed=3407,
        split_seeds=[11],
        test_ratio=0.2,
        val_ratio=0.1,
    )
    split_11 = bundle.manifest["splits"]["11"]
    train_ids = set(split_11["train_ids"])
    val_ids = set(split_11["val_ids"])
    test_ids = set(split_11["test_ids"])
    assert train_ids.isdisjoint(val_ids)
    assert train_ids.isdisjoint(test_ids)
    assert val_ids.isdisjoint(test_ids)
    all_ids = train_ids | val_ids | test_ids
    assert all_ids == {record.sample_id for record in sample_inventory}


def test_generate_split_bundle_uses_fallback_strata_for_test_holdout() -> None:
    from obb_baseline.splitters import SampleRecord, generate_split_bundle

    class_names = ("pattern_a", "pattern_b", "pattern_c")
    image_path = Path("image.png")
    ann_path = Path("ann.txt")
    records = [
        SampleRecord(
            sample_id="neg_1",
            stem="neg_1",
            image_path=image_path,
            ann_path=ann_path,
            class_names=class_names,
            instance_count=0,
            is_negative=True,
            class_mask="000",
            instance_count_bucket="0",
        ),
        SampleRecord(
            sample_id="neg_2",
            stem="neg_2",
            image_path=image_path,
            ann_path=ann_path,
            class_names=class_names,
            instance_count=0,
            is_negative=True,
            class_mask="000",
            instance_count_bucket="0",
        ),
        SampleRecord(
            sample_id="neg_3",
            stem="neg_3",
            image_path=image_path,
            ann_path=ann_path,
            class_names=class_names,
            instance_count=0,
            is_negative=True,
            class_mask="000",
            instance_count_bucket="0",
        ),
        SampleRecord(
            sample_id="pos_1",
            stem="pos_1",
            image_path=image_path,
            ann_path=ann_path,
            class_names=class_names,
            instance_count=1,
            is_negative=False,
            class_mask="100",
            instance_count_bucket="1",
        ),
        SampleRecord(
            sample_id="pos_2",
            stem="pos_2",
            image_path=image_path,
            ann_path=ann_path,
            class_names=class_names,
            instance_count=2,
            is_negative=False,
            class_mask="100",
            instance_count_bucket="2-4",
        ),
        SampleRecord(
            sample_id="pos_3",
            stem="pos_3",
            image_path=image_path,
            ann_path=ann_path,
            class_names=class_names,
            instance_count=5,
            is_negative=False,
            class_mask="100",
            instance_count_bucket=">=5",
        ),
    ]

    bundle = generate_split_bundle(
        records,
        dataset_name="synthetic_fallback",
        holdout_seed=11,
        split_seeds=[11],
        test_ratio=1 / 3,
        val_ratio=0.15,
    )
    test_ids = bundle.manifest["splits"]["11"]["test_ids"]
    assert len([sample_id for sample_id in test_ids if sample_id.startswith("neg_")]) == 1
    assert len([sample_id for sample_id in test_ids if sample_id.startswith("pos_")]) == 1


@pytest.mark.parametrize(
    "test_ratio,val_ratio",
    [
        (-0.1, 0.1),
        (1.0, 0.1),
        (0.1, -0.1),
        (0.1, 1.0),
        (0.6, 0.5),
    ],
)
def test_generate_split_bundle_rejects_invalid_ratios(
    sample_inventory,
    test_ratio: float,
    val_ratio: float,
) -> None:
    from obb_baseline.splitters import generate_split_bundle

    with pytest.raises(ValueError):
        generate_split_bundle(
            sample_inventory,
            dataset_name="tiny_dota_export",
            holdout_seed=3407,
            split_seeds=[11],
            test_ratio=test_ratio,
            val_ratio=val_ratio,
        )


def test_scan_dota_export_requires_labeltxt_dir(tmp_path: Path) -> None:
    from obb_baseline.splitters import scan_dota_export

    dota_root = tmp_path / "missing_labeltxt"
    (dota_root / "train" / "images").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        scan_dota_export(dota_root, class_names=("pattern_a",))


def test_scan_dota_export_requires_existing_image(tmp_path: Path) -> None:
    from obb_baseline.splitters import scan_dota_export

    dota_root = tmp_path / "missing_image"
    ann_dir = dota_root / "train" / "labelTxt"
    ann_dir.mkdir(parents=True)
    (ann_dir / "sample_missing.txt").write_text(
        "0 0 10 0 10 10 0 10 pattern_a 0\n",
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        scan_dota_export(dota_root, class_names=("pattern_a",))
