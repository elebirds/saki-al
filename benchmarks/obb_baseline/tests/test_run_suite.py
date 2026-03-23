from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from obb_baseline.registry import ModelSpec


def load_run_suite_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_suite.py"
    spec = importlib.util.spec_from_file_location("obb_run_suite", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_split_manifest(path: Path, *, split_seeds: list[int], test_ids: list[str]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "dataset_name": "tiny_dota_export",
        "holdout_seed": 3407,
        "test_ratio": 0.15,
        "val_ratio": 0.15,
        "split_seeds": split_seeds,
        "splits": {
            str(seed): {
                "train_ids": ["img_001", "img_002"],
                "val_ids": ["img_003"],
                "test_ids": list(test_ids),
            }
            for seed in split_seeds
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "benchmark_name": "fedo_part2_v1",
        "models": ["yolo11m_obb", "oriented_rcnn_r50"],
        "runtime": {"device": "0"},
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_metrics(
    run_dir: Path,
    *,
    model_name: str,
    split_seed: int,
    train_seed: int,
    status: str,
    m_ap50_95: float = 0.44,
    m_ap50: float = 0.61,
    precision: float = 0.7,
    recall: float = 0.6,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "benchmark_name": "fedo_part2_v1",
        "split_manifest_hash": "hash",
        "model_name": model_name,
        "preset": "stub-preset",
        "holdout_seed": 3407,
        "split_seed": split_seed,
        "train_seed": train_seed,
        "status": status,
        "mAP50_95": m_ap50_95,
        "mAP50": m_ap50,
        "precision": precision,
        "recall": recall,
        "f1": 0.0,
        "train_time_sec": None,
        "infer_time_ms": None,
        "peak_mem_mb": None,
        "param_count": None,
        "checkpoint_size_mb": None,
        "artifact_paths": {},
    }
    (run_dir / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_main_skips_succeeded_run_and_still_writes_suite_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    config_path = benchmark_root / "config.yaml"
    write_config(config_path)

    run_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    write_metrics(
        run_dir,
        model_name="oriented_rcnn_r50",
        split_seed=11,
        train_seed=101,
        status="succeeded",
    )

    calls = {
        "dispatch_runner": 0,
        "execute_launch": 0,
        "parse_and_write_outputs": 0,
    }

    def _dispatch_runner(**_kwargs):
        calls["dispatch_runner"] += 1
        return module.RunnerLaunch(command=["echo", "unexpected"], cwd=str(benchmark_root), extra_env={})

    def _execute_launch(*_args, **_kwargs):
        calls["execute_launch"] += 1
        return subprocess.CompletedProcess(args=["echo", "unexpected"], returncode=0, stdout="", stderr="")

    def _parse_and_write_outputs(**_kwargs):
        calls["parse_and_write_outputs"] += 1

    monkeypatch.setattr(module, "dispatch_runner", _dispatch_runner)
    monkeypatch.setattr(module, "execute_launch", _execute_launch)
    monkeypatch.setattr(module, "parse_and_write_outputs", _parse_and_write_outputs)

    exit_code = module.main(
        [
            "--config",
            str(config_path),
            "--benchmark-root",
            str(benchmark_root),
            "--models",
            "oriented_rcnn_r50",
            "--split-seeds",
            "11",
            "--train-seeds",
            "101",
        ]
    )
    assert exit_code == 0
    assert (benchmark_root / "config.snapshot.yaml").is_file()
    assert (benchmark_root / "summary.csv").is_file()
    assert (benchmark_root / "leaderboard.csv").is_file()
    assert (benchmark_root / "summary.md").is_file()
    assert calls == {
        "dispatch_runner": 0,
        "execute_launch": 0,
        "parse_and_write_outputs": 0,
    }


def test_main_reruns_failed_run_when_flag_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    manifest = write_split_manifest(
        benchmark_root / "split_manifest.json",
        split_seeds=[11],
        test_ids=["img_004"],
    )
    config_path = benchmark_root / "config.yaml"
    write_config(config_path)

    run_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    write_metrics(
        run_dir,
        model_name="oriented_rcnn_r50",
        split_seed=11,
        train_seed=101,
        status="failed",
    )

    dispatch_calls: list[dict[str, object]] = []
    execute_calls: list[tuple[object, object]] = []
    parse_calls: list[dict[str, object]] = []

    def _dispatch_runner(**kwargs):
        dispatch_calls.append(kwargs)
        return module.RunnerLaunch(command=["echo", "ok"], cwd=str(benchmark_root), extra_env={})

    def _execute_launch(launch, env):
        execute_calls.append((launch, env))
        return subprocess.CompletedProcess(args=launch.command, returncode=0, stdout="ok\n", stderr="")

    def _parse_and_write_outputs(**kwargs):
        parse_calls.append(kwargs)
        write_metrics(
            run_dir,
            model_name="oriented_rcnn_r50",
            split_seed=11,
            train_seed=101,
            status="succeeded",
        )

    monkeypatch.setattr(module, "dispatch_runner", _dispatch_runner)
    monkeypatch.setattr(module, "execute_launch", _execute_launch)
    monkeypatch.setattr(module, "parse_and_write_outputs", _parse_and_write_outputs)

    exit_code = module.main(
        [
            "--config",
            str(config_path),
            "--benchmark-root",
            str(benchmark_root),
            "--models",
            "oriented_rcnn_r50",
            "--split-seeds",
            "11",
            "--train-seeds",
            "101",
            "--rerun-failed",
        ]
    )
    assert exit_code == 0
    assert manifest["holdout_seed"] == 3407
    assert len(dispatch_calls) == 1
    assert len(execute_calls) == 1
    assert len(parse_calls) == 1


def test_should_skip_run_respects_rerun_failed_flag(tmp_path: Path) -> None:
    module = load_run_suite_module()
    run_dir = tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    run_dir.mkdir(parents=True, exist_ok=True)

    assert module.should_skip_run(run_dir=run_dir, rerun_failed=False) is False

    (run_dir / "metrics.json").write_text(
        json.dumps({"status": "succeeded"}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert module.should_skip_run(run_dir=run_dir, rerun_failed=False) is True
    assert module.should_skip_run(run_dir=run_dir, rerun_failed=True) is True

    (run_dir / "metrics.json").write_text(
        json.dumps({"status": "failed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert module.should_skip_run(run_dir=run_dir, rerun_failed=False) is True
    assert module.should_skip_run(run_dir=run_dir, rerun_failed=True) is False

    (run_dir / "metrics.json").write_text("{bad_json", encoding="utf-8")
    assert module.should_skip_run(run_dir=run_dir, rerun_failed=False) is False


def test_main_writes_standard_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    config_path = benchmark_root / "config.yaml"
    write_config(config_path)

    run_dir = benchmark_root / "records" / "yolo11m_obb" / "split-11" / "seed-101"

    monkeypatch.setattr(
        module,
        "dispatch_runner",
        lambda **_: module.RunnerLaunch(command=["echo", "ok"], cwd=str(benchmark_root), extra_env={}),
    )
    monkeypatch.setattr(
        module,
        "execute_launch",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["echo", "ok"],
            returncode=0,
            stdout="train ok\n",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        module,
        "parse_and_write_outputs",
        lambda **_: write_metrics(
            run_dir,
            model_name="yolo11m_obb",
            split_seed=11,
            train_seed=101,
            status="succeeded",
        ),
    )

    exit_code = module.main(
        [
            "--config",
            str(config_path),
            "--benchmark-root",
            str(benchmark_root),
            "--models",
            "yolo11m_obb",
            "--split-seeds",
            "11",
            "--train-seeds",
            "101",
        ]
    )
    assert exit_code == 0
    assert (run_dir / "metrics.json").is_file()
    assert (run_dir / "run_config.json").is_file()
    assert (run_dir / "status.json").is_file()
    assert (run_dir / "stdout.log").is_file()
    assert (run_dir / "stderr.log").is_file()
    assert json.loads((run_dir / "status.json").read_text(encoding="utf-8"))["status"] == "succeeded"


def test_parse_and_write_outputs_delegates_to_mmrotate_runner_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_run_suite_module()
    run_dir = tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    work_dir = tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    run_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"holdout_seed": 3407}
    captured: dict[str, object] = {}

    def _fake_parse_mmrotate_outputs(**kwargs):
        captured.update(kwargs)
        (run_dir / "metrics.json").write_text(
            json.dumps({"status": "succeeded"}, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(module, "parse_mmrotate_outputs", _fake_parse_mmrotate_outputs)

    module.parse_and_write_outputs(
        model_spec=ModelSpec(
            model_name="oriented_rcnn_r50",
            runner_name="mmrotate",
            env_name="mmrotate",
            data_view="dota",
            preset="oriented-rcnn-r50-fpn",
        ),
        benchmark_name="fedo_part2_v1",
        manifest=manifest,
        manifest_hash="abc123",
        split_seed=11,
        train_seed=101,
        run_dir=run_dir,
        work_dir=work_dir,
        execution_status="succeeded",
    )

    assert captured["work_dir"] == work_dir
    assert captured["metrics_path"] == run_dir / "metrics.json"
    assert captured["execution_status"] == "succeeded"
    assert captured["run_metadata"].model_name == "oriented_rcnn_r50"
    assert captured["run_metadata"].split_seed == 11
    assert captured["run_metadata"].train_seed == 101


def test_parse_and_write_outputs_delegates_to_yolo_runner_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_run_suite_module()
    run_dir = tmp_path / "records" / "yolo11m_obb" / "split-11" / "seed-101"
    work_dir = tmp_path / "workdirs" / "yolo11m_obb" / "split-11" / "seed-101"
    run_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"holdout_seed": 3407}
    captured: dict[str, object] = {}

    def _fake_parse_yolo_outputs(**kwargs):
        captured.update(kwargs)
        (run_dir / "metrics.json").write_text(
            json.dumps({"status": "succeeded"}, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(module, "parse_yolo_outputs", _fake_parse_yolo_outputs)

    module.parse_and_write_outputs(
        model_spec=ModelSpec(
            model_name="yolo11m_obb",
            runner_name="yolo",
            env_name="yolo",
            data_view="yolo_obb",
            preset="yolo11m-obb",
        ),
        benchmark_name="fedo_part2_v1",
        manifest=manifest,
        manifest_hash="abc123",
        split_seed=11,
        train_seed=101,
        run_dir=run_dir,
        work_dir=work_dir,
        execution_status="succeeded",
    )

    assert captured["work_dir"] == work_dir
    assert captured["metrics_path"] == run_dir / "metrics.json"
    assert captured["status_path"] == run_dir / "yolo_status.json"
    assert captured["execution_status"] == "succeeded"
    assert captured["run_metadata"].model_name == "yolo11m_obb"
    assert captured["run_metadata"].split_seed == 11
    assert captured["run_metadata"].train_seed == 101
