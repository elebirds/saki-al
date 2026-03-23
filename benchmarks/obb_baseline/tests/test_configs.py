from pathlib import Path

import yaml


def test_benchmark_configs_contain_required_keys() -> None:
    payload = yaml.safe_load(Path("benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml").read_text(encoding="utf-8"))
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["dataset"]["dota_root"] == "__SET_ME__/dota_export"
    assert payload["dataset"]["yolo_obb_root"] == "__SET_ME__/yolo_obb_export"
    assert payload["dataset"]["classes"] == ["pattern_a", "pattern_b", "pattern_c"]
    assert payload["splits"]["holdout_seed"] == 3407
    assert payload["splits"]["split_seeds"] == [11, 17, 23]
    assert payload["splits"]["train_seeds"] == [101, 202, 303]
    assert payload["splits"]["test_ratio"] == 0.15
    assert payload["splits"]["val_ratio"] == 0.15
    assert payload["runtime"]["device"] == "0"
    assert payload["runtime"]["score_thr"] == 0.05
    assert payload["runtime"]["link_mode"] == "symlink"
    assert payload["models"] == [
        "yolo11m_obb",
        "oriented_rcnn_r50",
        "roi_transformer_r50",
        "r3det_r50",
        "rtmdet_rotated_m",
    ]


def test_part3_config_uses_independent_benchmark_name_and_split_manifest_pointer() -> None:
    payload = yaml.safe_load(Path("benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml").read_text(encoding="utf-8"))
    assert payload["benchmark_name"] == "fedo_part3_orcnn_v1"
    assert payload["dataset"]["dota_root"] == "__SET_ME__/dota_export"
    assert payload["dataset"]["yolo_obb_root"] == "__SET_ME__/yolo_obb_export"
    assert payload["dataset"]["classes"] == ["pattern_a", "pattern_b", "pattern_c"]
    assert payload["models"] == ["oriented_rcnn_r50"]
    assert payload["split_manifest_path"] == ""
    assert payload["runtime"]["device"] == "0"
    assert payload["runtime"]["score_thr"] == 0.05
    assert payload["runtime"]["link_mode"] == "symlink"


def test_readme_mentions_required_commands_and_artifacts() -> None:
    text = Path("benchmarks/obb_baseline/README.md").read_text(encoding="utf-8")
    assert "uv sync --project benchmarks/obb_baseline/envs/mmrotate" in text
    assert "uv sync --project benchmarks/obb_baseline/envs/yolo" in text
    assert "env PYTHONPATH=benchmarks/obb_baseline/src" in text
    assert "uv run --with pyyaml" in text
    assert "python benchmarks/obb_baseline/scripts/split_dataset.py" in text
    assert "python benchmarks/obb_baseline/scripts/run_suite.py" in text
    assert "benchmarks/obb_baseline/scripts/split_dataset.py" in text
    assert "benchmarks/obb_baseline/scripts/run_suite.py" in text
    assert "--dota-root" in text
    assert "--classes" in text
    assert "--out-dir" in text
    assert "--holdout-seed" in text
    assert "--benchmark-root" in text
    assert "--config" in text
    assert "--models" in text
    assert "--split-seeds" in text
    assert "--train-seeds" in text
    assert "split_manifest.json" in text
    assert "Stage 0 smoke" in text
    assert "summary.csv" in text
    assert "leaderboard.csv" in text
    assert "summary.md" in text
    assert "runs/obb_baseline/<benchmark_name>/" in text
    assert "runs/obb_baseline/<benchmark_name>/benchmark.local.yaml" in text
    assert "benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml" in text
    assert "默认配置是模板" in text
    assert "benchmark.smoke.local.yaml" in text
