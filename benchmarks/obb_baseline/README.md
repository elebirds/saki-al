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
`split_dataset.py` 不会直接消费 benchmark YAML，需通过 CLI 参数（如 `--dota-root`、`--classes`、`--out-dir`）生成 `split_manifest.json`。  
`run_suite.py` 除了 `--config` 外，仍需要通过 CLI 传入 `--models`、`--split-seeds`、`--train-seeds` 等组合参数。  
`benchmark.fedo_part3_orcnn_v1.yaml` 中的 `split_manifest_path` 当前为保留字段；Phase 1 仍读取 `<benchmark-root>/split_manifest.json`。  
进行 Stage 0 smoke 时，需要先在 `runs/` 下生成本地可执行配置（如 `benchmark.smoke.local.yaml`），不要直接修改仓库模板。

## 平台边界说明

- Darwin 本机已验证可跑通：全量测试（`env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests -q`，结果 `84 passed`）、`uv sync --project benchmarks/obb_baseline/envs/yolo`、`split_dataset.py`、本地 smoke 配置生成、suite 编排与统一产物契约检查。
- Darwin 本机未通过：`uv sync --project benchmarks/obb_baseline/envs/mmrotate`。原因是当前锁定的 `mmcv` wheel（`mmcv-2.0.1-cp310-cp310-manylinux1_x86_64.whl`）仅支持 manylinux x86_64，与 `macosx_arm64` 不兼容。
- 因此，真实 mmrotate 环境安装与 AutoDL 单机单卡训练验证应在 AutoDL Ubuntu/CUDA 环境执行。
