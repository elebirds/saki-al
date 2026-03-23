from __future__ import annotations

import importlib.util
import json
import os
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


def test_build_child_env_prefixes_pythonpath_and_clears_virtual_env() -> None:
    module = load_run_suite_module()
    env = module.build_child_env(
        base_env={
            "PYTHONPATH": "/tmp/existing",
            "VIRTUAL_ENV": "/tmp/outer-venv",
            "KEEP_ME": "1",
        }
    )

    expected_src = str((Path(module.__file__).resolve().parent.parent / "src").resolve())
    assert env["PYTHONPATH"] == f"{expected_src}{os.pathsep}/tmp/existing"
    assert "VIRTUAL_ENV" not in env
    assert env["KEEP_ME"] == "1"


def test_dispatch_runner_for_mmrotate_uses_view_dir_as_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_run_suite_module()
    run_dir = tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    work_dir = tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    view_dir = tmp_path / "views" / "dota" / "split-11"
    run_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    view_dir.mkdir(parents=True, exist_ok=True)

    render_calls: dict[str, object] = {}
    build_calls: dict[str, object] = {}

    def _fake_render_mmrotate_config(**kwargs):
        render_calls.update(kwargs)
        return "# generated config\n"

    def _fake_build_mmrotate_train_command(**kwargs):
        build_calls.update(kwargs)
        return [
            "uv",
            "run",
            "--project",
            "benchmarks/obb_baseline/envs/mmrotate",
            "python",
            "-m",
            "obb_baseline.runners_mmrotate",
            "--config",
            str(kwargs["generated_config"]),
        ]

    monkeypatch.setattr(module, "render_mmrotate_config", _fake_render_mmrotate_config)
    monkeypatch.setattr(module, "build_mmrotate_train_command", _fake_build_mmrotate_train_command)

    launch = module.dispatch_runner(
        model_spec=ModelSpec(
            model_name="oriented_rcnn_r50",
            runner_name="mmrotate",
            env_name="mmrotate",
            data_view="dota",
            preset="oriented-rcnn-r50-fpn",
        ),
        config={
            "dataset": {"classes": ["pattern_a", "pattern_b", "pattern_c"]},
            "runtime": {"device": "0", "score_thr": 0.15},
        },
        split_seed=11,
        train_seed=101,
        run_dir=run_dir,
        work_dir=work_dir,
        view_dir=view_dir,
    )

    generated_config = run_dir / "mmrotate.generated.py"
    assert render_calls["data_root"] == view_dir
    assert render_calls["work_dir"] == work_dir
    assert render_calls["train_seed"] == 101
    assert render_calls["score_thr"] == 0.15
    assert render_calls["classes"] == ("pattern_a", "pattern_b", "pattern_c")
    assert generated_config.read_text(encoding="utf-8") == "# generated config\n"
    assert build_calls["generated_config"] == generated_config
    assert build_calls["work_dir"] == work_dir
    assert build_calls["train_seed"] == 101
    assert build_calls["device"] == "0"
    assert "--config" in launch.command
    assert str(generated_config) in launch.command


def test_main_emits_view_progress_logs_before_runner_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    config_path = benchmark_root / "config.yaml"
    write_config(config_path)

    observed_steps: list[str] = []
    view_dir = benchmark_root / "views" / "dota" / "split-11"
    run_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"

    def _fake_ensure_view_materialized(**_kwargs):
        observed_steps.append("view")
        view_dir.mkdir(parents=True, exist_ok=True)
        return view_dir

    def _fake_dispatch_runner(**_kwargs):
        observed_steps.append("dispatch")
        return module.RunnerLaunch(command=["echo", "ok"], cwd=str(benchmark_root), extra_env={})

    monkeypatch.setattr(module, "ensure_view_materialized", _fake_ensure_view_materialized)
    monkeypatch.setattr(module, "dispatch_runner", _fake_dispatch_runner)
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
            model_name="oriented_rcnn_r50",
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
            "oriented_rcnn_r50",
            "--split-seeds",
            "11",
            "--train-seeds",
            "101",
        ]
    )

    assert exit_code == 0
    assert observed_steps == ["view", "dispatch"]
    out = capsys.readouterr().out
    assert "[VIEW]" in out
    assert "model=oriented_rcnn_r50" in out
    assert "split=11" in out
    assert "action=materialize" in out
    assert "action=ready" in out


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


def test_main_emits_progress_logs_for_skip_and_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    config_path = benchmark_root / "config.yaml"
    write_config(config_path)

    skipped_run_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    write_metrics(
        skipped_run_dir,
        model_name="oriented_rcnn_r50",
        split_seed=11,
        train_seed=101,
        status="failed",
    )
    executed_run_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-202"

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
        lambda **kwargs: write_metrics(
            executed_run_dir if kwargs["train_seed"] == 202 else skipped_run_dir,
            model_name="oriented_rcnn_r50",
            split_seed=11,
            train_seed=int(kwargs["train_seed"]),
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
            "oriented_rcnn_r50",
            "--split-seeds",
            "11",
            "--train-seeds",
            "101,202",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[SKIP]" in out
    assert "split=11" in out
    assert "train=101" in out
    assert "[START]" in out
    assert "train=202" in out
    assert "[DONE]" in out
    assert "[SUITE]" in out


def test_main_status_tracks_final_failed_metrics_even_when_returncode_is_zero(
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
            status="failed",
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
    status_payload = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    metrics_payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert status_payload["returncode"] == 0
    assert status_payload["execution_status"] == "succeeded"
    assert metrics_payload["status"] == "failed"
    assert status_payload["status"] == "failed"


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
    assert captured["execution_status"] == "succeeded"
    assert captured["run_metadata"].model_name == "yolo11m_obb"
    assert captured["run_metadata"].split_seed == 11
    assert captured["run_metadata"].train_seed == 101
