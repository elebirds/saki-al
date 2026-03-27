# OBB Baseline Benchmark

## 环境准备

说明：`yolo` env 已在 Darwin 本机验证可执行 `uv sync`。`mmrotate` env 的真实安装不应以 Darwin 本机通过为目标，需在 AutoDL Ubuntu/CUDA 执行（当前锁定 `mmcv` wheel 为 manylinux x86_64）。

```bash
uv sync --project benchmarks/obb_baseline/envs/mmrotate
uv sync --project benchmarks/obb_baseline/envs/yolo
```

## 数据划分

`split_dataset.py` 示例：

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml \
  python benchmarks/obb_baseline/scripts/split_dataset.py \
  --dota-root /path/to/dota_export \
  --classes pattern_a,pattern_b,pattern_c \
  --out-dir runs/obb_baseline/fedo_part2_smoke \
  --holdout-seed 3407 \
  --split-seeds 11
```

## 执行基准

`run_suite.py` 示例：

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml \
  python benchmarks/obb_baseline/scripts/run_suite.py \
  --config runs/obb_baseline/fedo_part2_v1/benchmark.local.yaml \
  --benchmark-root runs/obb_baseline/fedo_part2_v1 \
  --models yolo11m_obb,oriented_rcnn_r50 \
  --split-seeds 11 \
  --train-seeds 101
```

## Stage 0 smoke

推荐按以下步骤执行：

1. 准备导出数据：先准备最小可用 `dota_export` 与 `yolo_obb_export`。
2. 运行 `split_dataset.py`：输出到 `runs/obb_baseline/fedo_part2_smoke/`。
3. 由模板生成本地配置：在 `runs/obb_baseline/fedo_part2_smoke/` 下生成 `benchmark.smoke.local.yaml`。
4. 运行 `run_suite.py`：

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml \
  python benchmarks/obb_baseline/scripts/run_suite.py \
  --config runs/obb_baseline/fedo_part2_smoke/benchmark.smoke.local.yaml \
  --benchmark-root runs/obb_baseline/fedo_part2_smoke \
  --models yolo11m_obb,oriented_rcnn_r50 \
  --split-seeds 11 \
  --train-seeds 101
```

5. 验证统一产物契约：确认 `records/.../metrics.json`（yolo/mmrotate）存在且包含标准字段，并确认 `summary.csv`、`leaderboard.csv`、`summary.md` 存在。当前本机合成 smoke 的验证脚本输出为 `stage0-smoke-verified`。

说明：当前本机合成 smoke 主要用于验证 harness/产物链路。该次验证中 `yolo_status=failed`（本地 `device=0` 且无 CUDA）、`mmrotate_status=failed`（`mmcv` wheel 平台不兼容），不代表 benchmark harness 本身损坏；真实训练效果验证应在目标 Linux/CUDA 环境完成。

## 产物目录

运行输出位于 `runs/obb_baseline/<benchmark_name>/`，至少包含：

- `summary.csv`
- `leaderboard.csv`
- `summary.md`

## 配置说明

仓库内默认配置是模板，不应直接改为本机路径。  
先将模板（如 `benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml`）拷贝到 `runs/obb_baseline/<benchmark_name>/benchmark.local.yaml`，并将 `__SET_ME__` 替换为本机真实路径，再作为 `run_suite.py --config` 输入。  
若只想先验证两条 runner 链路是否完整可出结果，可从 `benchmarks/obb_baseline/configs/benchmark.fedo_part2_quickcheck_v1.yaml` 起步。  
`split_dataset.py` 不会直接消费 benchmark YAML，需通过 CLI 参数（如 `--dota-root`、`--classes`、`--out-dir`）生成 `split_manifest.json`。  
`run_suite.py` 除了 `--config` 外，仍需要通过 CLI 传入 `--models`、`--split-seeds`、`--train-seeds` 等组合参数。  
`benchmark.fedo_part3_orcnn_v1.yaml` 中的 `split_manifest_path` 当前为保留字段；Phase 1 仍读取 `<benchmark-root>/split_manifest.json`。  
进行 Stage 0 smoke 时，需要先在 `runs/` 下生成本地可执行配置（如 `benchmark.smoke.local.yaml`），不要直接修改仓库模板。

常用 runtime 字段：

- `stream_logs`: 是否实时透传子进程日志到当前终端，同时仍写入 `stdout.log` / `stderr.log`
- `mmrotate_batch_size`: MMRotate `train_dataloader.batch_size`
- `mmrotate_workers`: MMRotate `train/val/test_dataloader.num_workers`
- `mmrotate_amp`: 是否将 MMRotate `optim_wrapper` 切到 `AmpOptimWrapper`
- `mmrotate_epochs`: MMRotate 专用训练轮数，默认 `36`
- `yolo_imgsz`: YOLO 专用输入尺寸，默认 `960`，与当前 `960x540` 原图尺寸更匹配
- `yolo_batch_size`: YOLO 专用 batch size，优先级高于通用 `batch_size`
- `yolo_workers`: YOLO dataloader worker 数
- `yolo_amp`: 是否为 YOLO 训练显式开启 AMP
- `yolo_mosaic`: YOLO Mosaic 概率；当前默认 `0.0`
- `yolo_close_mosaic`: YOLO 关闭 Mosaic 的最后若干 epoch；当前默认 `0`
- `yolo_epochs`: YOLO 专用训练轮数，优先级高于通用 `epochs`，默认 `200`

结果语义：

- YOLO：先训练，再自动执行一次 `test` 集评测；最终写入汇总的 `mAP50_95 / mAP50 / precision / recall / f1` 来自 `test_eval/results.csv`
- MMRotate：`mAP50_95 / mAP50` 来自 `runner.test()` 的 `DOTA` 指标；`precision / recall / f1` 由自定义 `BenchmarkDOTAMetric` 在 `test` 阶段按 `score_thr` 与 `IoU=0.5` 统计

在 4090 上建议先从以下本地配置起步：

```yaml
runtime:
  device: "0"
  score_thr: 0.05
  link_mode: symlink
  stream_logs: true
  mmrotate_batch_size: 4
  mmrotate_workers: 8
  mmrotate_amp: true
  mmrotate_epochs: 36
  yolo_imgsz: 960
  yolo_batch_size: 16
  yolo_workers: 16
  yolo_amp: true
  yolo_mosaic: 0.0
  yolo_close_mosaic: 0
  yolo_epochs: 200
```

## 平台边界说明

- Darwin 本机已验证可跑通：全量测试（`env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests -q`，结果 `103 passed`）、`uv sync --project benchmarks/obb_baseline/envs/yolo`、`split_dataset.py`、本地 smoke 配置生成、suite 编排与统一产物契约检查。
- Darwin 本机未通过：`uv sync --project benchmarks/obb_baseline/envs/mmrotate`。原因是当前锁定的 `mmcv` wheel（`mmcv-2.0.1-cp310-cp310-manylinux1_x86_64.whl`）仅支持 manylinux x86_64，与 `macosx_arm64` 不兼容。
- 因此，真实 mmrotate 环境安装与 AutoDL 单机单卡训练验证应在 AutoDL Ubuntu/CUDA 环境执行。
