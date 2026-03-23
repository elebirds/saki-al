# OBB Baseline Benchmark

## 环境准备

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

Stage 0 smoke 示例：

前置条件：`runs/obb_baseline/fedo_part2_smoke/split_manifest.json` 已由 `split_dataset.py` 生成。

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml \
  python benchmarks/obb_baseline/scripts/run_suite.py \
  --config runs/obb_baseline/fedo_part2_smoke/benchmark.smoke.local.yaml \
  --benchmark-root runs/obb_baseline/fedo_part2_smoke \
  --models oriented_rcnn_r50 \
  --split-seeds 11 \
  --train-seeds 101
```

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
