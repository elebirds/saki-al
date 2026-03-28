"""Benchmark suite orchestrator."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import selectors
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml


def _load_obb_modules():
    try:
        from obb_baseline.dataset_views import materialize_dota_view, materialize_yolo_view
        from obb_baseline.registry import ModelSpec, load_model_registry
        from obb_baseline.runners_mmrotate import (
            RunMetadata as MMRotateRunMetadata,
            build_mmrotate_train_command,
            parse_mmrotate_outputs,
            render_mmrotate_config,
        )
        from obb_baseline.runners_yolo import (
            RunMetadata as YoloRunMetadata,
            build_yolo_test_command,
            build_yolo_train_command,
            parse_yolo_outputs,
        )
        from obb_baseline.summary import collect_suite_outputs, write_suite_outputs

        return {
            "ModelSpec": ModelSpec,
            "load_model_registry": load_model_registry,
            "materialize_dota_view": materialize_dota_view,
            "materialize_yolo_view": materialize_yolo_view,
            "MMRotateRunMetadata": MMRotateRunMetadata,
            "build_mmrotate_train_command": build_mmrotate_train_command,
            "parse_mmrotate_outputs": parse_mmrotate_outputs,
            "render_mmrotate_config": render_mmrotate_config,
            "YoloRunMetadata": YoloRunMetadata,
            "build_yolo_test_command": build_yolo_test_command,
            "build_yolo_train_command": build_yolo_train_command,
            "parse_yolo_outputs": parse_yolo_outputs,
            "collect_suite_outputs": collect_suite_outputs,
            "write_suite_outputs": write_suite_outputs,
        }
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("obb_baseline"):
            raise
        script_dir = Path(__file__).resolve().parent
        fallback_src = script_dir.parent / "src"
        if fallback_src.is_dir():
            sys.path.insert(0, str(fallback_src))
            return _load_obb_modules()
        raise


_MOD = _load_obb_modules()
ModelSpec = _MOD["ModelSpec"]
load_model_registry = _MOD["load_model_registry"]
materialize_dota_view = _MOD["materialize_dota_view"]
materialize_yolo_view = _MOD["materialize_yolo_view"]
MMRotateRunMetadata = _MOD["MMRotateRunMetadata"]
build_mmrotate_train_command = _MOD["build_mmrotate_train_command"]
parse_mmrotate_outputs = _MOD["parse_mmrotate_outputs"]
render_mmrotate_config = _MOD["render_mmrotate_config"]
YoloRunMetadata = _MOD["YoloRunMetadata"]
build_yolo_test_command = _MOD["build_yolo_test_command"]
build_yolo_train_command = _MOD["build_yolo_train_command"]
parse_yolo_outputs = _MOD["parse_yolo_outputs"]
collect_suite_outputs = _MOD["collect_suite_outputs"]
write_suite_outputs = _MOD["write_suite_outputs"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OBB benchmark suite")
    parser.add_argument("--config", required=True)
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--split-seeds", required=True)
    parser.add_argument("--train-seeds", required=True)
    parser.add_argument("--rerun-failed", action="store_true")
    return parser.parse_args(argv)


class RunnerLaunch:
    def __init__(self, *, command: list[str], cwd: str, extra_env: dict[str, str]) -> None:
        self.command = command
        self.cwd = cwd
        self.extra_env = extra_env


def _combine_process_results(
    first: subprocess.CompletedProcess[str],
    second: subprocess.CompletedProcess[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[first.args, second.args],
        returncode=second.returncode,
        stdout=(first.stdout or "") + (second.stdout or ""),
        stderr=(first.stderr or "") + (second.stderr or ""),
    )


def _emit_progress(tag: str, message: str) -> None:
    print(f"[{tag}] {message}", flush=True)


def _format_command(command: list[str]) -> str:
    return shlex.join(command)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"配置必须是映射: {path}")
    return payload


def _read_json_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 必须是对象: {path}")
    return payload


def _parse_csv_items(raw: str) -> list[str]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        raise ValueError("列表参数不能为空")
    return items


def _parse_csv_ints(raw: str) -> list[int]:
    values: list[int] = []
    for item in _parse_csv_items(raw):
        values.append(int(item))
    return values


def _parse_runtime_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"无效的布尔运行时配置: {value!r}")


def _parse_runtime_int(value: object, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _parse_runtime_float(value: object, *, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def dispatch_runner(
    *,
    model_spec: ModelSpec,
    config: Mapping[str, object],
    split_seed: int,
    train_seed: int,
    run_dir: Path,
    work_dir: Path,
    view_dir: Path,
) -> RunnerLaunch:
    runtime = config.get("runtime")
    runtime_mapping = runtime if isinstance(runtime, Mapping) else {}
    device = str(runtime_mapping.get("device", "0"))

    if model_spec.runner_name == "yolo":
        yolo_epochs_raw = runtime_mapping.get("yolo_epochs")
        if yolo_epochs_raw is None:
            yolo_epochs_raw = runtime_mapping.get("epochs")
        yolo_batch_size_raw = runtime_mapping.get("yolo_batch_size")
        if yolo_batch_size_raw is None:
            yolo_batch_size_raw = runtime_mapping.get("batch_size")
        yolo_imgsz_raw = runtime_mapping.get("yolo_imgsz")
        if yolo_imgsz_raw is None:
            yolo_imgsz_raw = runtime_mapping.get("imgsz")
        command = build_yolo_train_command(
            preset=model_spec.preset,
            dataset_yaml=view_dir / "dataset.yaml",
            run_dir=run_dir,
            work_dir=work_dir,
            train_seed=train_seed,
            device=device,
            imgsz=_parse_runtime_int(yolo_imgsz_raw, default=960),
            epochs=_parse_runtime_int(yolo_epochs_raw, default=200),
            batch_size=_parse_runtime_int(yolo_batch_size_raw, default=16),
            workers=_parse_runtime_int(runtime_mapping.get("yolo_workers"), default=16),
            amp=_parse_runtime_bool(runtime_mapping.get("yolo_amp"), default=True),
            mosaic=_parse_runtime_float(runtime_mapping.get("yolo_mosaic"), default=0.0),
            close_mosaic=_parse_runtime_int(runtime_mapping.get("yolo_close_mosaic"), default=0),
        )
        return RunnerLaunch(command=command, cwd=str(_repo_root()), extra_env={})

    if model_spec.runner_name == "mmrotate":
        dataset = config.get("dataset")
        dataset_mapping = dataset if isinstance(dataset, Mapping) else {}
        classes = tuple(str(item) for item in dataset_mapping.get("classes", ()))
        score_thr = float(runtime_mapping.get("score_thr", 0.05))
        mmrotate_batch_size = _parse_runtime_int(
            runtime_mapping.get("mmrotate_batch_size"),
            default=4,
        )
        mmrotate_workers = _parse_runtime_int(
            runtime_mapping.get("mmrotate_workers"),
            default=8,
        )
        mmrotate_amp = _parse_runtime_bool(
            runtime_mapping.get("mmrotate_amp"),
            default=True,
        )
        mmrotate_epochs = _parse_runtime_int(
            runtime_mapping.get("mmrotate_epochs"),
            default=36,
        )
        mmrotate_train_aug_preset = str(runtime_mapping.get("mmrotate_train_aug_preset", "default"))
        mmrotate_anchor_ratio_preset = str(runtime_mapping.get("mmrotate_anchor_ratio_preset", "default"))
        mmrotate_roi_bbox_loss_preset = str(runtime_mapping.get("mmrotate_roi_bbox_loss_preset", "smooth_l1"))
        mmrotate_boundary_aux_preset = str(runtime_mapping.get("mmrotate_boundary_aux_preset", "none"))
        mmrotate_topology_aux_preset = str(runtime_mapping.get("mmrotate_topology_aux_preset", "none"))
        generated_config = run_dir / "mmrotate.generated.py"
        generated_config.write_text(
            render_mmrotate_config(
                model_name=model_spec.model_name,
                data_root=view_dir,
                work_dir=work_dir,
                train_seed=train_seed,
                score_thr=score_thr,
                classes=classes,
                mmrotate_batch_size=mmrotate_batch_size,
                mmrotate_workers=mmrotate_workers,
                mmrotate_amp=mmrotate_amp,
                mmrotate_epochs=mmrotate_epochs,
                mmrotate_train_aug_preset=mmrotate_train_aug_preset,
                mmrotate_anchor_ratio_preset=mmrotate_anchor_ratio_preset,
                mmrotate_roi_bbox_loss_preset=mmrotate_roi_bbox_loss_preset,
                mmrotate_boundary_aux_preset=mmrotate_boundary_aux_preset,
                mmrotate_topology_aux_preset=mmrotate_topology_aux_preset,
            ),
            encoding="utf-8",
        )
        command = build_mmrotate_train_command(
            model_name=model_spec.model_name,
            run_dir=run_dir,
            generated_config=generated_config,
            work_dir=work_dir,
            train_seed=train_seed,
            device=device,
        )
        return RunnerLaunch(command=command, cwd=str(_repo_root()), extra_env={})

    raise ValueError(f"unsupported runner: {model_spec.runner_name}")


def execute_launch(
    launch: RunnerLaunch,
    env: Mapping[str, str],
    stream_logs: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged_env = dict(env)
    merged_env.update(launch.extra_env)
    process = subprocess.Popen(
        launch.command,
        cwd=launch.cwd,
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    decoders = {
        "stdout": codecs.getincrementaldecoder("utf-8")(errors="replace"),
        "stderr": codecs.getincrementaldecoder("utf-8")(errors="replace"),
    }
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, data=("stdout", stdout_chunks))
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, data=("stderr", stderr_chunks))

    while selector.get_map():
        for key, _ in selector.select():
            stream = key.fileobj
            stream_name, chunks = key.data
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                tail = decoders[stream_name].decode(b"", final=True)
                if tail:
                    chunks.append(tail)
                    if stream_logs:
                        sink = sys.stdout if stream_name == "stdout" else sys.stderr
                        sink.write(tail)
                        sink.flush()
                selector.unregister(stream)
                stream.close()
                continue
            text = decoders[stream_name].decode(chunk, final=False)
            chunks.append(text)
            if stream_logs:
                sink = sys.stdout if stream_name == "stdout" else sys.stderr
                sink.write(text)
                sink.flush()

    return subprocess.CompletedProcess(
        args=launch.command,
        returncode=process.wait(),
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


def maybe_run_yolo_test_evaluation(
    *,
    model_spec: ModelSpec,
    config: Mapping[str, object],
    view_dir: Path,
    work_dir: Path,
    train_result: subprocess.CompletedProcess[str],
    child_env: Mapping[str, str],
    stream_logs: bool,
) -> subprocess.CompletedProcess[str]:
    if model_spec.runner_name != "yolo" or train_result.returncode != 0:
        return train_result

    runtime = config.get("runtime")
    runtime_mapping = runtime if isinstance(runtime, Mapping) else {}
    yolo_batch_size_raw = runtime_mapping.get("yolo_batch_size")
    if yolo_batch_size_raw is None:
        yolo_batch_size_raw = runtime_mapping.get("batch_size")
    yolo_imgsz_raw = runtime_mapping.get("yolo_imgsz")
    if yolo_imgsz_raw is None:
        yolo_imgsz_raw = runtime_mapping.get("imgsz")
    test_launch = RunnerLaunch(
        command=build_yolo_test_command(
            checkpoint_path=work_dir / "weights" / "best.pt",
            dataset_yaml=view_dir / "dataset.yaml",
            work_dir=work_dir,
            device=str(runtime_mapping.get("device", "0")),
            imgsz=_parse_runtime_int(yolo_imgsz_raw, default=960),
            batch_size=_parse_runtime_int(yolo_batch_size_raw, default=16),
            workers=_parse_runtime_int(runtime_mapping.get("yolo_workers"), default=16),
        ),
        cwd=str(_repo_root()),
        extra_env={},
    )
    _emit_progress(
        "CMD",
        f"cwd={test_launch.cwd} cmd={_format_command(test_launch.command)}",
    )
    test_result = execute_launch(test_launch, env=child_env, stream_logs=stream_logs)
    return _combine_process_results(train_result, test_result)


def parse_and_write_outputs(
    *,
    model_spec: ModelSpec,
    benchmark_name: str,
    manifest: Mapping[str, object],
    manifest_hash: str,
    split_seed: int,
    train_seed: int,
    run_dir: Path,
    work_dir: Path,
    execution_status: str,
) -> None:
    holdout_seed = int(manifest.get("holdout_seed", 0))

    if model_spec.runner_name == "mmrotate":
        parse_mmrotate_outputs(
            work_dir=work_dir,
            metrics_path=run_dir / "metrics.json",
            run_metadata=MMRotateRunMetadata(
                benchmark_name=benchmark_name,
                split_manifest_hash=manifest_hash,
                model_name=model_spec.model_name,
                preset=model_spec.preset,
                holdout_seed=holdout_seed,
                split_seed=split_seed,
                train_seed=train_seed,
                artifact_paths={},
                train_time_sec=None,
                infer_time_ms=None,
                peak_mem_mb=None,
                param_count=None,
                checkpoint_size_mb=None,
            ),
            execution_status=execution_status,
        )
        return

    if model_spec.runner_name == "yolo":
        parse_yolo_outputs(
            work_dir=work_dir,
            metrics_path=run_dir / "metrics.json",
            run_metadata=YoloRunMetadata(
                benchmark_name=benchmark_name,
                split_manifest_hash=manifest_hash,
                model_name=model_spec.model_name,
                preset=model_spec.preset,
                holdout_seed=holdout_seed,
                split_seed=split_seed,
                train_seed=train_seed,
                artifact_paths={},
                train_time_sec=None,
                infer_time_ms=None,
                peak_mem_mb=None,
                param_count=None,
                checkpoint_size_mb=None,
            ),
            execution_status=execution_status,
        )
        return

    raise ValueError(f"unsupported runner: {model_spec.runner_name}")


def should_skip_run(
    *,
    run_dir: Path,
    rerun_failed: bool = False,
) -> bool:
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        return False
    try:
        payload = _read_json_mapping(metrics_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    status = str(payload.get("status", ""))
    if status == "succeeded":
        return True
    if status == "failed":
        return not rerun_failed
    return False


def resolve_run_dir(
    *,
    benchmark_root: Path,
    model_name: str,
    split_seed: int,
    train_seed: int,
) -> Path:
    run_dir = (
        benchmark_root / "records" / model_name / f"split-{split_seed}" / f"seed-{train_seed}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_config_snapshot(path: Path, config: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def write_run_config(*, run_dir: Path, payload: Mapping[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_config.json").write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_status_and_logs(
    *,
    run_dir: Path,
    result: subprocess.CompletedProcess[str],
) -> str:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "stdout.log").write_text(result.stdout or "", encoding="utf-8")
    (run_dir / "stderr.log").write_text(result.stderr or "", encoding="utf-8")
    status = "succeeded" if result.returncode == 0 else "failed"
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": status,
                "returncode": int(result.returncode),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return status


def update_status_from_metrics(
    *,
    run_dir: Path,
    execution_status: str,
    returncode: int,
) -> str:
    final_status = execution_status
    metrics_path = run_dir / "metrics.json"
    if metrics_path.exists():
        try:
            payload = _read_json_mapping(metrics_path)
        except (OSError, json.JSONDecodeError, ValueError):
            payload = {}
        metrics_status = payload.get("status")
        if metrics_status in {"succeeded", "failed"}:
            final_status = str(metrics_status)

    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": final_status,
                "execution_status": execution_status,
                "returncode": int(returncode),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return final_status


def build_child_env(
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.pop("VIRTUAL_ENV", None)
    src_path = str((Path(__file__).resolve().parent.parent / "src").resolve())
    existing = env.get("PYTHONPATH", "")
    if existing:
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing}"
    else:
        env["PYTHONPATH"] = src_path
    return env


def _split_ids_from_manifest(manifest: Mapping[str, object], split_seed: int) -> dict[str, list[str]]:
    splits = manifest.get("splits")
    if not isinstance(splits, Mapping):
        raise ValueError("split_manifest.json 缺少 splits 映射")
    split_item = splits.get(str(split_seed))
    if not isinstance(split_item, Mapping):
        raise ValueError(f"split_manifest.json 缺少 split_seed={split_seed}")
    return {
        "train": list(split_item.get("train_ids", []) or []),
        "val": list(split_item.get("val_ids", []) or []),
        "test": list(split_item.get("test_ids", []) or []),
    }


def ensure_view_materialized(
    *,
    benchmark_root: Path,
    model_spec: ModelSpec,
    split_seed: int,
    manifest: Mapping[str, object],
    config: Mapping[str, object],
) -> Path:
    out_dir = benchmark_root / "views" / model_spec.data_view / f"split-{split_seed}"
    split_ids = _split_ids_from_manifest(manifest, split_seed)

    runtime = config.get("runtime")
    runtime_mapping = runtime if isinstance(runtime, Mapping) else {}
    link_mode = str(runtime_mapping.get("link_mode", "symlink"))

    dataset = config.get("dataset")
    if not isinstance(dataset, Mapping):
        out_dir.mkdir(parents=True, exist_ok=True)
        if model_spec.data_view == "yolo_obb":
            dataset_yaml = out_dir / "dataset.yaml"
            if not dataset_yaml.exists():
                dataset_yaml.write_text(
                    (
                        f'path: "{out_dir}"\n'
                        'train: "images/train"\n'
                        'val: "images/val"\n'
                        'test: "images/test"\n'
                        "nc: 0\n"
                        "names: []\n"
                    ),
                    encoding="utf-8",
                )
        return out_dir

    dota_root = Path(str(dataset["dota_root"])).resolve()
    if model_spec.data_view == "dota":
        return materialize_dota_view(
            dota_root=dota_root,
            split_ids=split_ids,
            out_dir=out_dir,
            link_mode=link_mode,
        )
    if model_spec.data_view == "yolo_obb":
        yolo_root = Path(str(dataset["yolo_obb_root"])).resolve()
        classes = tuple(str(item) for item in dataset.get("classes", ()))
        return materialize_yolo_view(
            dota_root=dota_root,
            yolo_root=yolo_root,
            split_ids=split_ids,
            class_names=classes,
            out_dir=out_dir,
            link_mode=link_mode,
        )
    raise ValueError(f"unsupported data_view: {model_spec.data_view}")


def _resolve_benchmark_name(config: Mapping[str, object]) -> str:
    for key in ("benchmark_name", "name"):
        value = config.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("config 缺少 benchmark_name/name")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).resolve()
    benchmark_root = Path(args.benchmark_root).resolve()
    benchmark_root.mkdir(parents=True, exist_ok=True)

    config = _read_yaml_mapping(config_path)
    benchmark_name = _resolve_benchmark_name(config)

    manifest_path = benchmark_root / "split_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"缺少 split manifest: {manifest_path}")
    manifest = _read_json_mapping(manifest_path)

    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    model_registry = load_model_registry(
        _repo_root() / "benchmarks" / "obb_baseline" / "configs" / "models.yaml"
    )
    selected_models = _parse_csv_items(args.models)
    selected_split_seeds = _parse_csv_ints(args.split_seeds)
    selected_train_seeds = _parse_csv_ints(args.train_seeds)
    total_runs = len(selected_models) * len(selected_split_seeds) * len(selected_train_seeds)
    skipped_runs = 0
    succeeded_runs = 0
    failed_runs = 0

    write_config_snapshot(benchmark_root / "config.snapshot.yaml", config)
    child_env = build_child_env()
    runtime = config.get("runtime")
    runtime_mapping = runtime if isinstance(runtime, Mapping) else {}
    stream_logs = _parse_runtime_bool(runtime_mapping.get("stream_logs"), default=False)

    for model_name in selected_models:
        model_spec = model_registry[model_name]
        for split_seed in selected_split_seeds:
            view_root = benchmark_root / "views" / model_spec.data_view / f"split-{split_seed}"
            _emit_progress(
                "VIEW",
                (
                    f"model={model_name} split={split_seed} "
                    f"view={model_spec.data_view} action=materialize path={view_root}"
                ),
            )
            view_dir = ensure_view_materialized(
                benchmark_root=benchmark_root,
                model_spec=model_spec,
                split_seed=split_seed,
                manifest=manifest,
                config=config,
            )
            _emit_progress(
                "VIEW",
                (
                    f"model={model_name} split={split_seed} "
                    f"view={model_spec.data_view} action=ready path={view_dir}"
                ),
            )
            for train_seed in selected_train_seeds:
                run_dir = resolve_run_dir(
                    benchmark_root=benchmark_root,
                    model_name=model_name,
                    split_seed=split_seed,
                    train_seed=train_seed,
                )
                if should_skip_run(run_dir=run_dir, rerun_failed=args.rerun_failed):
                    skipped_runs += 1
                    _emit_progress(
                        "SKIP",
                        (
                            f"model={model_name} split={split_seed} train={train_seed} "
                            f"reason=existing_metrics rerun_failed={args.rerun_failed}"
                        ),
                    )
                    continue

                work_dir = (
                    benchmark_root
                    / "workdirs"
                    / model_name
                    / f"split-{split_seed}"
                    / f"seed-{train_seed}"
                )
                work_dir.mkdir(parents=True, exist_ok=True)

                launch = dispatch_runner(
                    model_spec=model_spec,
                    config=config,
                    split_seed=split_seed,
                    train_seed=train_seed,
                    run_dir=run_dir,
                    work_dir=work_dir,
                    view_dir=view_dir,
                )
                _emit_progress(
                    "START",
                    (
                        f"model={model_name} split={split_seed} train={train_seed} "
                        f"runner={model_spec.runner_name} run_dir={run_dir}"
                    ),
                )
                _emit_progress(
                    "CMD",
                    f"cwd={launch.cwd} cmd={_format_command(launch.command)}",
                )
                write_run_config(
                    run_dir=run_dir,
                    payload={
                        "benchmark_name": benchmark_name,
                        "config_path": str(config_path),
                        "benchmark_root": str(benchmark_root),
                        "manifest_path": str(manifest_path),
                        "split_manifest_hash": manifest_hash,
                        "model_name": model_name,
                        "runner_name": model_spec.runner_name,
                        "env_name": model_spec.env_name,
                        "data_view": model_spec.data_view,
                        "preset": model_spec.preset,
                        "split_seed": split_seed,
                        "train_seed": train_seed,
                        "view_dir": str(view_dir),
                        "work_dir": str(work_dir),
                        "command": launch.command,
                        "cwd": launch.cwd,
                        "extra_env": launch.extra_env,
                    },
                )
                train_result = execute_launch(launch, env=child_env, stream_logs=stream_logs)
                result = maybe_run_yolo_test_evaluation(
                    model_spec=model_spec,
                    config=config,
                    view_dir=view_dir,
                    work_dir=work_dir,
                    train_result=train_result,
                    child_env=child_env,
                    stream_logs=stream_logs,
                )
                execution_status = write_status_and_logs(run_dir=run_dir, result=result)
                parse_and_write_outputs(
                    model_spec=model_spec,
                    benchmark_name=benchmark_name,
                    manifest=manifest,
                    manifest_hash=manifest_hash,
                    split_seed=split_seed,
                    train_seed=train_seed,
                    run_dir=run_dir,
                    work_dir=work_dir,
                    execution_status=execution_status,
                )
                final_status = update_status_from_metrics(
                    run_dir=run_dir,
                    execution_status=execution_status,
                    returncode=result.returncode,
                )
                if final_status == "succeeded":
                    succeeded_runs += 1
                else:
                    failed_runs += 1
                _emit_progress(
                    "DONE",
                    (
                        f"model={model_name} split={split_seed} train={train_seed} "
                        f"status={final_status} returncode={result.returncode} "
                        f"stdout={run_dir / 'stdout.log'} stderr={run_dir / 'stderr.log'}"
                    ),
                )

    outputs = collect_suite_outputs(
        benchmark_name=benchmark_name,
        benchmark_root=benchmark_root,
    )
    write_suite_outputs(outputs, benchmark_root)
    _emit_progress(
        "SUITE",
        (
            f"benchmark={benchmark_name} root={benchmark_root} total={total_runs} "
            f"succeeded={succeeded_runs} failed={failed_runs} skipped={skipped_runs}"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
