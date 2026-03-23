from __future__ import annotations


def test_scan_dota_export_builds_expected_sample_fields(tiny_dota_export) -> None:
    from obb_baseline.splitters import scan_dota_export

    records = scan_dota_export(
        tiny_dota_export,
        class_names=("pattern_a", "pattern_b", "pattern_c"),
    )
    assert records[0].sample_id == records[0].stem
    assert records[0].class_mask in {
        "000",
        "100",
        "010",
        "001",
        "110",
        "101",
        "011",
        "111",
    }
    assert records[0].instance_count_bucket in {"0", "1", "2-4", ">=5"}


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
    assert split_11["train_ids"] != split_17["train_ids"]


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
