# OBB Benchmark Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 Phase 1 OBB benchmark harness：从导出后的全集切分数据、按统一 split 运行 5 个 OBB 基线模型、收集统一 `metrics.json`，并输出 `summary.csv`、`leaderboard.csv`、`summary.md`。

**Architecture:** 保持对外表面极小，只暴露 `split_dataset.py` 和 `run_suite.py` 两个 CLI。编排层保持框架无关，数据切分、数据视图、结果汇总都放在轻量内部模块中；重框架训练与评测全部通过 `uv` 子进程进入 `mmrotate` / `yolo` 两个隔离环境，最后统一落到标准化记录目录。

**Tech Stack:** Python 3.12、`uv`、`pytest`、`PyYAML`、标准库 `argparse/pathlib/subprocess/json/csv/hashlib/statistics`、OneDL MMRotate 栈、Ultralytics YOLO。

---

## File Structure

以下文件是 Phase 1 的最小实现集合。默认全部新建，除非任务中另有说明。

- `benchmarks/obb_baseline/README.md`
  - 用户入口文档，说明 AutoDL 环境准备、两个 `uv` 环境安装、切分命令、suite 运行命令、Stage 0 smoke 命令。
- `benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml`
  - 第二部分实验默认配置。
- `benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml`
  - 第三部分复用配置模板，Phase 1 只要求文件存在且字段完整。
- `benchmarks/obb_baseline/configs/models.yaml`
  - 5 个模型的注册信息和默认 preset。
- `benchmarks/obb_baseline/envs/mmrotate/pyproject.toml`
  - `mmrotate` 环境固定依赖；`requires-python` 必须显式钉死为 `==3.12.*`。
- `benchmarks/obb_baseline/envs/mmrotate/uv.lock`
  - `mmrotate` 环境锁文件。
- `benchmarks/obb_baseline/envs/yolo/pyproject.toml`
  - `yolo` 环境固定依赖；`requires-python` 必须显式钉死为 `==3.12.*`。
- `benchmarks/obb_baseline/envs/yolo/uv.lock`
  - `yolo` 环境锁文件。
- `benchmarks/obb_baseline/scripts/split_dataset.py`
  - 只负责生成 `split_manifest.json` 和 `split_summary.json`。
- `benchmarks/obb_baseline/scripts/run_suite.py`
  - 只负责读取 split、按需物化视图、调度模型、写标准化记录、汇总结果。
- `benchmarks/obb_baseline/src/obb_baseline/__init__.py`
  - 包入口。
- `benchmarks/obb_baseline/src/obb_baseline/splitters.py`
  - 全集扫描、样本描述、三级回退分层、manifest/summary 生成。
- `benchmarks/obb_baseline/src/obb_baseline/dataset_views.py`
  - `DOTA` / `YOLO OBB` 视图物化、stem 对齐校验、软链接策略。
- `benchmarks/obb_baseline/src/obb_baseline/registry.py`
  - 模型注册表、环境映射、preset 与数据视图需求。
- `benchmarks/obb_baseline/src/obb_baseline/runners_mmrotate.py`
  - MMRotate 子进程命令构造、运行时配置渲染、原始指标解析、标准 `metrics.json` 写出。
- `benchmarks/obb_baseline/src/obb_baseline/runners_yolo.py`
  - YOLO 子进程命令构造、`results.csv` 解析、标准 `metrics.json` 写出。
- `benchmarks/obb_baseline/src/obb_baseline/summary.py`
  - 读取所有 `metrics.json`，生成 `summary.csv`、`leaderboard.csv`、`summary.md`。
- `benchmarks/obb_baseline/tests/conftest.py`
  - 生成最小 `DOTA` / `YOLO OBB` 导出目录的测试辅助函数。
- `benchmarks/obb_baseline/tests/test_scaffold.py`
  - benchmark 骨架存在性单测。
- `benchmarks/obb_baseline/tests/test_splitters.py`
  - 切分与统计单测。
- `benchmarks/obb_baseline/tests/test_split_dataset_cli.py`
  - `split_dataset.py` CLI 集成单测。
- `benchmarks/obb_baseline/tests/test_dataset_views.py`
  - 数据视图物化与 stem 对齐单测。
- `benchmarks/obb_baseline/tests/test_registry.py`
  - 5 模型注册信息单测。
- `benchmarks/obb_baseline/tests/test_envs.py`
  - 两个 `uv` 环境声明单测。
- `benchmarks/obb_baseline/tests/test_configs.py`
  - benchmark 配置文件完整性单测。
- `benchmarks/obb_baseline/tests/test_summary.py`
  - 汇总与排序单测。
- `benchmarks/obb_baseline/tests/test_runners_mmrotate.py`
  - MMRotate runner 命令与解析单测。
- `benchmarks/obb_baseline/tests/test_runners_yolo.py`
  - YOLO runner 命令与解析单测。
- `benchmarks/obb_baseline/tests/test_run_suite.py`
  - `run_suite.py` 的过滤、resume、记录目录和汇总生成单测。

实现约束：

- 不新增第三个长期环境。
- 不新增 `materialize_splits.py`。
- 不新增 `collect_results.py`。
- 不引入 HBB 逻辑。
- 不在编排层 import `onedl-mmrotate`、`onedl-mmcv`、`onedl-mmdetection`、`ultralytics`。

## Chunk 1: Skeleton And Split Pipeline

### Task 1: 搭建 benchmark 骨架与测试入口

**Files:**
- Create: `benchmarks/obb_baseline/README.md`
- Create: `benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml`
- Create: `benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml`
- Create: `benchmarks/obb_baseline/configs/models.yaml`
- Create: `benchmarks/obb_baseline/scripts/split_dataset.py`
- Create: `benchmarks/obb_baseline/scripts/run_suite.py`
- Create: `benchmarks/obb_baseline/src/obb_baseline/__init__.py`
- Create: `benchmarks/obb_baseline/tests/conftest.py`
- Create: `benchmarks/obb_baseline/tests/test_scaffold.py`

- [ ] **Step 1: 写一个失败的骨架测试**

```python
from pathlib import Path


def test_benchmark_skeleton_files_exist() -> None:
    required = [
        Path("benchmarks/obb_baseline/README.md"),
        Path("benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml"),
        Path("benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml"),
        Path("benchmarks/obb_baseline/configs/models.yaml"),
        Path("benchmarks/obb_baseline/scripts/split_dataset.py"),
        Path("benchmarks/obb_baseline/scripts/run_suite.py"),
        Path("benchmarks/obb_baseline/src/obb_baseline/__init__.py"),
    ]
    for path in required:
        assert path.exists(), f"missing: {path}"
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_scaffold.py::test_benchmark_skeleton_files_exist -q
```

Expected:

```text
FAIL ... missing: benchmarks/obb_baseline/README.md
```

- [ ] **Step 3: 创建最小骨架文件**

最小内容要求：

```python
# benchmarks/obb_baseline/src/obb_baseline/__init__.py
__all__ = []
```

```yaml
# benchmarks/obb_baseline/configs/models.yaml
models:
  yolo11m_obb:
    runner: yolo
    env: yolo
    data_view: yolo_obb
    preset: yolo11m-obb
  oriented_rcnn_r50:
    runner: mmrotate
    env: mmrotate
    data_view: dota
    preset: oriented-rcnn-r50-fpn
  roi_transformer_r50:
    runner: mmrotate
    env: mmrotate
    data_view: dota
    preset: roi-transformer-r50-fpn
  r3det_r50:
    runner: mmrotate
    env: mmrotate
    data_view: dota
    preset: r3det-r50-fpn
  rtmdet_rotated_m:
    runner: mmrotate
    env: mmrotate
    data_view: dota
    preset: rtmdet-rotated-m
```

README 先写成可解析的最小 stub，至少包含标题、范围说明和 “后续任务补全” 小节。

- [ ] **Step 4: 重新跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_scaffold.py::test_benchmark_skeleton_files_exist -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline
git commit -m "chore: scaffold obb benchmark skeleton"
```

### Task 2: 实现 `splitters.py`

**Files:**
- Create: `benchmarks/obb_baseline/src/obb_baseline/splitters.py`
- Create: `benchmarks/obb_baseline/tests/test_splitters.py`
- Modify: `benchmarks/obb_baseline/tests/conftest.py`

- [ ] **Step 1: 写 splitter 失败测试**

```python
def test_scan_dota_export_builds_expected_sample_fields(tiny_dota_export) -> None:
    from obb_baseline.splitters import scan_dota_export

    records = scan_dota_export(
        tiny_dota_export,
        class_names=("pattern_a", "pattern_b", "pattern_c"),
    )
    assert records[0].sample_id == records[0].stem
    assert records[0].class_mask in {"000", "100", "010", "001", "110", "101", "011", "111"}
    assert records[0].instance_count_bucket in {"0", "1", "2-4", ">=5"}


def test_resolve_fallback_level_downgrades_small_strata(sample_inventory_with_small_bucket) -> None:
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


def test_generate_split_bundle_keeps_test_fixed_when_split_seed_changes(sample_inventory) -> None:
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


def test_generate_split_bundle_converts_val_ratio_within_trainval(sample_inventory) -> None:
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


def test_generate_split_bundle_writes_manifest_and_summary_schema(sample_inventory) -> None:
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
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_splitters.py -q
```

Expected:

```text
FAIL ... ModuleNotFoundError: No module named 'obb_baseline.splitters'
```

- [ ] **Step 3: 先实现 `scan_dota_export`**

核心对象和函数直接按下面的形状实现：

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SampleRecord:
    sample_id: str
    stem: str
    image_path: Path
    ann_path: Path
    class_names: tuple[str, ...]
    instance_count: int
    is_negative: bool
    class_mask: str
    instance_count_bucket: str


def scan_dota_export(dota_root: Path, class_names: tuple[str, ...]) -> list[SampleRecord]:
    ann_dir = dota_root / "train" / "labelTxt"
    image_dir = dota_root / "train" / "images"
    records: list[SampleRecord] = []
    # 逐个读取 DOTA txt，构建 SampleRecord，并按 stem 排序返回。
    return records
```

此步只要求完成：

- 只从 `DOTA` 导出扫描全集
- 忽略 `imagesource:` / `gsd:` 行
- `sample_id` 直接使用 stem
- `class_mask` 顺序固定按配置中的 `class_names`
- `instance_count_bucket` 只允许：`0`、`1`、`2-4`、`>=5`

- [ ] **Step 4: 跑局部测试并确认扫描逻辑通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest \
  benchmarks/obb_baseline/tests/test_splitters.py::test_scan_dota_export_builds_expected_sample_fields -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: 再实现 `resolve_fallback_level`**

```python
def resolve_fallback_level(
    *,
    strict_key: str,
    class_key: str,
    neg_key: str,
    strict_counts: dict[str, int],
    class_counts: dict[str, int],
    neg_counts: dict[str, int],
) -> int:
    if strict_counts.get(strict_key, 0) >= 3:
        return 0
    if class_counts.get(class_key, 0) >= 3:
        return 1
    return 2
```

此步只要求完成：

- 三级回退严格按 spec：
  - `fallback_level = 0` 对应 `(is_negative, class_mask, instance_count_bucket)`
  - `fallback_level = 1` 对应 `(is_negative, class_mask)`
  - `fallback_level = 2` 对应 `(is_negative)`

- [ ] **Step 6: 跑局部测试并确认回退逻辑通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest \
  benchmarks/obb_baseline/tests/test_splitters.py::test_resolve_fallback_level_downgrades_small_strata -q
```

Expected:

```text
1 passed
```

- [ ] **Step 7: 再实现 `generate_split_bundle` 与 schema 组装**

```python
@dataclass(frozen=True)
class SplitBundle:
    dataset_name: str
    manifest: dict[str, object]
    summary: dict[str, object]


def generate_split_bundle(
    sample_inventory: list[SampleRecord],
    *,
    dataset_name: str,
    holdout_seed: int,
    split_seeds: list[int],
    test_ratio: float,
    val_ratio: float,
) -> SplitBundle:
    # 先用 holdout_seed 切固定 test，再对每个 split_seed 只切 train/val。
    # 最终返回 manifest 和 summary 两个 JSON 兼容 dict。
    return SplitBundle(dataset_name=dataset_name, manifest={}, summary={})
```

此步只要求完成：

- `dataset_name` 固定取 `dota_root.name`，也允许由调用方显式传入同名值
- `SplitBundle.manifest` 至少包含：
  - `dataset_name`
  - `holdout_seed`
  - `test_ratio`
  - `val_ratio`
  - `split_seeds`
  - `splits`
- `SplitBundle.summary["splits"][split_seed]` 至少包含：
  - `train_count`
  - `val_count`
  - `test_count`
  - `positive_ratio`
  - `negative_ratio`
  - `class_mask_distribution`
  - `instance_count_bucket_distribution`
- `SplitBundle.summary` 顶层至少包含：
  - `dataset_name`
  - `split_count`
  - `splits`
- `val_ratio` 先换算为 `trainval` 内比例
- `split_manifest` 与 `split_summary` 都要可 JSON 序列化

- [ ] **Step 8: 跑全量测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_splitters.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 9: 提交**

```bash
git add benchmarks/obb_baseline/src/obb_baseline/splitters.py benchmarks/obb_baseline/tests/conftest.py benchmarks/obb_baseline/tests/test_splitters.py
git commit -m "feat: add benchmark splitters"
```

### Task 3: 实现 `split_dataset.py` CLI

**Files:**
- Modify: `benchmarks/obb_baseline/scripts/split_dataset.py`
- Create: `benchmarks/obb_baseline/tests/test_split_dataset_cli.py`

- [ ] **Step 1: 写 CLI 失败测试**

```python
import json
import subprocess
import sys


def test_split_dataset_cli_writes_manifest_and_summary(tmp_path, tiny_dota_export) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "smoke_split"
    cmd = [
        sys.executable,
        "benchmarks/obb_baseline/scripts/split_dataset.py",
        "--dota-root",
        str(tiny_dota_export),
        "--classes",
        "pattern_a,pattern_b,pattern_c",
        "--out-dir",
        str(out_dir),
        "--holdout-seed",
        "3407",
        "--split-seeds",
        "11,17,23",
    ]
    subprocess.run(cmd, check=True)

    manifest = json.loads((out_dir / "split_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((out_dir / "split_summary.json").read_text(encoding="utf-8"))
    assert manifest["dataset_name"] == tiny_dota_export.name
    assert manifest["holdout_seed"] == 3407
    assert manifest["split_seeds"] == [11, 17, 23]
    assert set(manifest["splits"]["11"]) == {"train_ids", "val_ids", "test_ids"}
    assert manifest["splits"]["11"]["test_ids"] == manifest["splits"]["17"]["test_ids"]
    assert summary["split_count"] == 3
    assert "class_mask_distribution" in summary["splits"]["11"]


def test_split_dataset_cli_uses_default_ratios_when_not_overridden(tmp_path, tiny_dota_export) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "default_ratio_split"
    cmd = [
        sys.executable,
        "benchmarks/obb_baseline/scripts/split_dataset.py",
        "--dota-root",
        str(tiny_dota_export),
        "--classes",
        "pattern_a,pattern_b,pattern_c",
        "--out-dir",
        str(out_dir),
        "--holdout-seed",
        "3407",
        "--split-seeds",
        "11",
    ]
    subprocess.run(cmd, check=True)

    manifest = json.loads((out_dir / "split_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_ratio"] == 0.15
    assert manifest["val_ratio"] == 0.15
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_split_dataset_cli.py -q
```

Expected:

```text
FAIL ... split_dataset.py exited with non-zero status
```

- [ ] **Step 3: 实现 CLI**

实现要点：

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate benchmark split manifest from DOTA export")
    parser.add_argument("--dota-root", required=True)
    parser.add_argument("--classes", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--holdout-seed", type=int, required=True)
    parser.add_argument("--split-seeds", required=True)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dota_root = Path(args.dota_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    class_names = tuple(x.strip() for x in args.classes.split(",") if x.strip())
    split_seeds = [int(x.strip()) for x in args.split_seeds.split(",") if x.strip()]
    inventory = scan_dota_export(dota_root, class_names)
    bundle = generate_split_bundle(
        inventory,
        dataset_name=dota_root.name,
        holdout_seed=args.holdout_seed,
        split_seeds=split_seeds,
        test_ratio=args.test_ratio,
        val_ratio=args.val_ratio,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "split_manifest.json").write_text(json.dumps(bundle.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "split_summary.json").write_text(json.dumps(bundle.summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

CLI 参数固定为：

- `--dota-root`
- `--classes`
- `--out-dir`
- `--holdout-seed`
- `--split-seeds`
- `--test-ratio`
- `--val-ratio`

CLI 语义要求：

- `--split-seeds 11,17,23` 必须解析成 `list[int]`
- `--test-ratio` 和 `--val-ratio` 缺省值固定为 `0.15`
- 输出文件固定写到 `<out-dir>/split_manifest.json` 和 `<out-dir>/split_summary.json`
- `manifest["dataset_name"]` 固定取 `Path(args.dota_root).name`
- 脚本必须支持 `python benchmarks/obb_baseline/scripts/split_dataset.py ...` 直接执行

不要在这个脚本里做任何视图物化、模型注册、训练调度。

- [ ] **Step 4: 重新跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_split_dataset_cli.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/scripts/split_dataset.py benchmarks/obb_baseline/tests/test_split_dataset_cli.py
git commit -m "feat: add split dataset cli"
```

## Chunk 2: Data Views, Registry And Summary

### Task 4: 实现 `dataset_views.py`

**Files:**
- Create: `benchmarks/obb_baseline/src/obb_baseline/dataset_views.py`
- Create: `benchmarks/obb_baseline/tests/test_dataset_views.py`
- Modify: `benchmarks/obb_baseline/tests/conftest.py`

- [ ] **Step 1: 写视图物化失败测试**

```python
def test_materialize_dota_view_links_expected_subset(tmp_path, tiny_dota_export) -> None:
    from obb_baseline.dataset_views import materialize_dota_view

    split_ids = {"train": ["img_001", "img_002"], "val": ["img_003"], "test": ["img_004"]}
    out_dir = tmp_path / "views" / "split-11" / "dota"
    materialize_dota_view(
        dota_root=tiny_dota_export,
        split_ids=split_ids,
        out_dir=out_dir,
        link_mode="symlink",
    )
    assert (out_dir / "train" / "images" / "img_001.png").exists()
    assert not (out_dir / "train" / "images" / "img_004.png").exists()


def test_materialize_yolo_view_rejects_stem_mismatch(tmp_path, tiny_dota_export, tiny_yolo_export_with_mismatch) -> None:
    from obb_baseline.dataset_views import materialize_yolo_view

    split_ids = {"train": ["img_001"], "val": [], "test": []}
    with pytest.raises(ValueError, match="stem mismatch"):
        materialize_yolo_view(
            dota_root=tiny_dota_export,
            yolo_root=tiny_yolo_export_with_mismatch,
            split_ids=split_ids,
            class_names=("pattern_a", "pattern_b", "pattern_c"),
            out_dir=tmp_path / "views" / "split-11" / "yolo_obb",
            link_mode="symlink",
        )


def test_materialize_yolo_view_writes_dataset_yaml_and_falls_back_to_copy(tmp_path, tiny_dota_export, tiny_yolo_export, monkeypatch) -> None:
    from obb_baseline.dataset_views import materialize_yolo_view

    monkeypatch.setattr("obb_baseline.dataset_views.os.symlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no symlink")))
    out_dir = tmp_path / "views" / "split-11" / "yolo_obb"
    materialize_yolo_view(
        dota_root=tiny_dota_export,
        yolo_root=tiny_yolo_export,
        split_ids={"train": ["img_001"], "val": ["img_002"], "test": ["img_003"]},
        class_names=("pattern_a", "pattern_b", "pattern_c"),
        out_dir=out_dir,
        link_mode="symlink",
    )
    assert (out_dir / "dataset.yaml").exists()
    assert (out_dir / "images" / "train" / "img_001.png").exists()
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_dataset_views.py -q
```

Expected:

```text
FAIL ... ModuleNotFoundError: No module named 'obb_baseline.dataset_views'
```

- [ ] **Step 3: 实现视图物化**

核心 API：

```python
def materialize_dota_view(*, dota_root: Path, split_ids: dict[str, list[str]], out_dir: Path, link_mode: str = "symlink") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def materialize_yolo_view(
    *,
    dota_root: Path,
    yolo_root: Path,
    split_ids: dict[str, list[str]],
    class_names: tuple[str, ...],
    out_dir: Path,
    link_mode: str = "symlink",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir
```

实现要求：

- 默认使用软链接，失败时回退到复制
- `DOTA` 视图目录固定为：
  - `train/images`
  - `train/labelTxt`
  - `val/images`
  - `val/labelTxt`
  - `test/images`
  - `test/labelTxt`
- `YOLO OBB` 视图目录固定为：
  - `images/train`
  - `images/val`
  - `images/test`
  - `labels/train`
  - `labels/val`
  - `labels/test`
  - `dataset.yaml`
- `materialize_yolo_view` 必须先基于 stem 对齐校验 `DOTA` 与 `YOLO OBB`

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_dataset_views.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/src/obb_baseline/dataset_views.py benchmarks/obb_baseline/tests/conftest.py benchmarks/obb_baseline/tests/test_dataset_views.py
git commit -m "feat: add benchmark dataset views"
```

### Task 5: 实现 `registry.py`

**Files:**
- Create: `benchmarks/obb_baseline/src/obb_baseline/registry.py`
- Modify: `benchmarks/obb_baseline/configs/models.yaml`
- Create: `benchmarks/obb_baseline/tests/test_registry.py`

- [ ] **Step 1: 写 registry 失败测试**

```python
def test_load_model_registry_returns_five_expected_models() -> None:
    from obb_baseline.registry import load_model_registry

    registry = load_model_registry(Path("benchmarks/obb_baseline/configs/models.yaml"))
    assert set(registry) == {
        "yolo11m_obb",
        "oriented_rcnn_r50",
        "roi_transformer_r50",
        "r3det_r50",
        "rtmdet_rotated_m",
    }
    assert registry["yolo11m_obb"].env_name == "yolo"
    assert registry["oriented_rcnn_r50"].data_view == "dota"


def test_load_model_registry_rejects_invalid_runner_and_data_view(tmp_path) -> None:
    from obb_baseline.registry import load_model_registry

    bad = tmp_path / "bad_models.yaml"
    bad.write_text(
        "models:\\n  broken:\\n    runner: unknown\\n    env: mmrotate\\n    data_view: broken\\n    preset: broken\\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runner|data_view"):
        load_model_registry(bad)
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_registry.py::test_load_model_registry_returns_five_expected_models -q
```

Expected:

```text
FAIL ... ModuleNotFoundError: No module named 'obb_baseline.registry'
```

- [ ] **Step 3: 实现 registry**

核心对象：

```python
@dataclass(frozen=True)
class ModelSpec:
    model_name: str
    runner_name: str
    env_name: str
    data_view: str
    preset: str


def load_model_registry(path: Path) -> dict[str, ModelSpec]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    models = payload["models"]
    registry: dict[str, ModelSpec] = {}
    for name, spec in models.items():
        registry[name] = ModelSpec(
            model_name=name,
            runner_name=spec["runner"],
            env_name=spec["env"],
            data_view=spec["data_view"],
            preset=spec["preset"],
        )
    return registry
```

实现要求：

- 只允许 5 个模型
- `configs/models.yaml` 的 YAML schema 固定保留 `runner` / `env` 键名，不改成 `runner_name` / `env_name`
- `runner_name` 只允许：`mmrotate` / `yolo`
- `data_view` 只允许：`dota` / `yolo_obb`
- 读取异常时直接报清晰错误，不做隐式默认

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_registry.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/src/obb_baseline/registry.py benchmarks/obb_baseline/configs/models.yaml benchmarks/obb_baseline/tests/test_registry.py
git commit -m "feat: add benchmark model registry"
```

### Task 6: 实现 `summary.py`

**Files:**
- Create: `benchmarks/obb_baseline/src/obb_baseline/summary.py`
- Create: `benchmarks/obb_baseline/tests/test_summary.py`

- [ ] **Step 1: 写 summary 失败测试**

```python
def test_collect_suite_outputs_summary_and_leaderboard(tmp_path) -> None:
    from obb_baseline.summary import collect_suite_outputs

    records_dir = tmp_path / "records"
    write_metrics(records_dir / "yolo11m_obb" / "split-11" / "seed-101" / "metrics.json", map50_95=0.41, precision=0.7, recall=0.6)
    write_metrics(records_dir / "yolo11m_obb" / "split-11" / "seed-202" / "metrics.json", map50_95=0.43, precision=0.8, recall=0.6)
    write_metrics(records_dir / "yolo11m_obb" / "split-17" / "seed-101" / "metrics.json", map50_95=0.39, precision=0.75, recall=0.5)
    write_metrics(records_dir / "oriented_rcnn_r50" / "split-11" / "seed-101" / "metrics.json", map50_95=0.44, precision=0.82, recall=0.7)
    write_metrics(records_dir / "oriented_rcnn_r50" / "split-11" / "seed-202" / "metrics.json", map50_95=0.45, precision=0.81, recall=0.72)
    write_metrics(records_dir / "oriented_rcnn_r50" / "split-17" / "seed-101" / "metrics.json", map50_95=0.43, precision=0.79, recall=0.68)

    outputs = collect_suite_outputs(
        benchmark_name="fedo_part2_v1",
        benchmark_root=tmp_path,
    )
    assert outputs.leaderboard_rows[0]["model_name"] == "oriented_rcnn_r50"
    assert outputs.leaderboard_rows[0]["mAP50_95_mean"] == pytest.approx(0.4375, abs=1e-6)
    assert outputs.leaderboard_rows[1]["mAP50_95_mean"] == pytest.approx(0.405, abs=1e-6)
    assert outputs.summary_rows[0]["model_name"] <= outputs.summary_rows[-1]["model_name"]
    assert outputs.summary_rows[0]["f1"] == pytest.approx(2 * 0.7 * 0.6 / (0.7 + 0.6), abs=1e-6)


def test_write_suite_outputs_writes_three_files(tmp_path) -> None:
    from obb_baseline.summary import collect_suite_outputs, write_suite_outputs

    records_dir = tmp_path / "records"
    write_metrics(records_dir / "oriented_rcnn_r50" / "split-11" / "seed-101" / "metrics.json", map50_95=0.44, precision=0.8, recall=0.7)
    outputs = collect_suite_outputs(
        benchmark_name="fedo_part2_v1",
        benchmark_root=tmp_path,
    )
    write_suite_outputs(outputs, tmp_path)
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "leaderboard.csv").exists()
    assert (tmp_path / "summary.md").exists()


def test_summary_md_uses_precision_best_wording_not_comprehensive_best(tmp_path) -> None:
    from obb_baseline.summary import collect_suite_outputs, render_summary_markdown

    records_dir = tmp_path / "records"
    write_metrics(records_dir / "oriented_rcnn_r50" / "split-11" / "seed-101" / "metrics.json", map50_95=0.44, precision=0.8, recall=0.7)
    outputs = collect_suite_outputs(
        benchmark_name="fedo_part2_v1",
        benchmark_root=tmp_path,
    )
    markdown = render_summary_markdown(outputs)
    assert "精度最佳模型" in markdown
    assert "综合最优模型" not in markdown
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_summary.py -q
```

Expected:

```text
FAIL ... ModuleNotFoundError: No module named 'obb_baseline.summary'
```

- [ ] **Step 3: 实现汇总模块**

核心 API：

```python
def load_metrics_rows(records_root: Path) -> list[dict[str, object]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in records_root.glob("*/*/*/metrics.json")]


def collect_suite_outputs(*, benchmark_name: str, benchmark_root: Path) -> SummaryOutputs:
    rows = load_metrics_rows(benchmark_root / "records")
    return SummaryOutputs(benchmark_name=benchmark_name, summary_rows=rows, leaderboard_rows=[])


def render_summary_markdown(outputs: SummaryOutputs) -> str:
    best = outputs.leaderboard_rows[0]["model_name"]
    return f"# {outputs.benchmark_name}\\n\\n精度最佳模型：{best}"


def write_suite_outputs(outputs: SummaryOutputs, benchmark_root: Path) -> None:
    (benchmark_root / "summary.md").write_text(render_summary_markdown(outputs), encoding="utf-8")
```

实现要求：

- `collect_suite_outputs` 只做内存聚合，不负责落盘
- `write_suite_outputs` 专职写出 `summary.csv`、`leaderboard.csv`、`summary.md`
- 聚合规则严格按 spec：
  - 先同一 `split_seed` 内跨 `train_seed` 聚合
  - 再跨 `split_seed` 聚合
- `f1` 固定按 `2PR / (P + R)` 计算
- `leaderboard.csv` 只按总 `mAP50_95 mean` 排序
- `summary.csv` 默认按 `model_name`、`split_seed`、`train_seed` 升序
- `summary.md` 默认跟随 `leaderboard.csv` 的排序，并使用“精度最佳模型”措辞
- 工程补充字段允许为空，但不能阻塞汇总

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_summary.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/src/obb_baseline/summary.py benchmarks/obb_baseline/tests/test_summary.py
git commit -m "feat: add benchmark summary outputs"
```

## Chunk 3: Environments, Runners And Suite Orchestration

### Task 7: 固定两个 `uv` 环境

**Files:**
- Create: `benchmarks/obb_baseline/envs/mmrotate/pyproject.toml`
- Create: `benchmarks/obb_baseline/envs/mmrotate/uv.lock`
- Create: `benchmarks/obb_baseline/envs/yolo/pyproject.toml`
- Create: `benchmarks/obb_baseline/envs/yolo/uv.lock`
- Create: `benchmarks/obb_baseline/tests/test_envs.py`

- [ ] **Step 1: 给环境文件写失败测试**

```python
import tomllib
from pathlib import Path


def test_env_projects_pin_python_312_and_expected_packages() -> None:
    mmrotate = tomllib.loads(Path("benchmarks/obb_baseline/envs/mmrotate/pyproject.toml").read_text(encoding="utf-8"))
    yolo = tomllib.loads(Path("benchmarks/obb_baseline/envs/yolo/pyproject.toml").read_text(encoding="utf-8"))

    assert mmrotate["project"]["requires-python"] == "==3.12.*"
    assert yolo["project"]["requires-python"] == "==3.12.*"
    assert "torch==2.9.1" in mmrotate["project"]["dependencies"]
    assert "torchvision==0.24.1" in mmrotate["project"]["dependencies"]
    assert "onedl-mmengine==0.10.9" in mmrotate["project"]["dependencies"]
    assert "onedl-mmcv==2.3.2.post2" in mmrotate["project"]["dependencies"]
    assert "onedl-mmdetection==3.4.5" in mmrotate["project"]["dependencies"]
    assert "onedl-mmrotate==1.1.0.post1" in mmrotate["project"]["dependencies"]
    assert "torch==2.10.0" in yolo["project"]["dependencies"]
    assert "torchvision==0.25.0" in yolo["project"]["dependencies"]
    assert "ultralytics==8.4.14" in yolo["project"]["dependencies"]


def test_env_lock_files_exist_after_locking() -> None:
    assert Path("benchmarks/obb_baseline/envs/mmrotate/uv.lock").exists()
    assert Path("benchmarks/obb_baseline/envs/yolo/uv.lock").exists()
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_envs.py -q
```

Expected:

```text
FAIL ... FileNotFoundError: benchmarks/obb_baseline/envs/mmrotate/pyproject.toml
```

- [ ] **Step 3: 创建两个环境项目**

`benchmarks/obb_baseline/envs/mmrotate/pyproject.toml` 至少包含：

```toml
[project]
name = "obb-benchmark-mmrotate-env"
version = "0.1.0"
requires-python = "==3.12.*"
dependencies = [
  "torch==2.9.1",
  "torchvision==0.24.1",
  "onedl-mmengine==0.10.9",
  "onedl-mmcv==2.3.2.post2",
  "onedl-mmdetection==3.4.5",
  "onedl-mmrotate==1.1.0.post1",
  "pyyaml>=6.0",
]
```

`benchmarks/obb_baseline/envs/yolo/pyproject.toml` 至少包含：

```toml
[project]
name = "obb-benchmark-yolo-env"
version = "0.1.0"
requires-python = "==3.12.*"
dependencies = [
  "torch==2.10.0",
  "torchvision==0.25.0",
  "ultralytics==8.4.14",
  "pyyaml>=6.0",
]
```

然后生成锁文件：

```bash
uv lock --project benchmarks/obb_baseline/envs/mmrotate
uv lock --project benchmarks/obb_baseline/envs/yolo
```

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_envs.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/envs benchmarks/obb_baseline/tests/test_envs.py
git commit -m "chore: pin benchmark runtime environments"
```

### Task 8: 实现 `runners_yolo.py`

**Files:**
- Create: `benchmarks/obb_baseline/src/obb_baseline/runners_yolo.py`
- Create: `benchmarks/obb_baseline/tests/test_runners_yolo.py`

- [ ] **Step 1: 写 YOLO runner 失败测试**

```python
import json
import pytest


def test_build_yolo_command_uses_yolo_env_and_dataset_yaml(tmp_path) -> None:
    from obb_baseline.runners_yolo import build_yolo_train_command

    command = build_yolo_train_command(
        preset="yolo11m-obb",
        dataset_yaml=tmp_path / "dataset.yaml",
        run_dir=tmp_path / "records" / "yolo11m_obb" / "split-11" / "seed-101",
        work_dir=tmp_path / "workdirs" / "yolo11m_obb" / "split-11" / "seed-101",
        train_seed=101,
        device="0",
        imgsz=1024,
        epochs=36,
        batch_size=2,
    )
    assert command[:4] == [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
    ]
    assert "train" in command
    assert "task=obb" in command
    assert "model=yolo11m-obb" in command
    assert f"data={tmp_path / 'dataset.yaml'}" in command
    assert f"project={tmp_path / 'workdirs' / 'yolo11m_obb' / 'split-11'}" in command
    assert "name=seed-101" in command
    assert "seed=101" in command
    assert "device=0" in command
    assert "imgsz=1024" in command
    assert "epochs=36" in command
    assert "batch=2" in command


def test_parse_yolo_results_csv_returns_full_metric_contract(tmp_path) -> None:
    from obb_baseline.runners_yolo import parse_yolo_results_csv

    results_csv = tmp_path / "results.csv"
    results_csv.write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\\n0.7,0.4,0.8,0.6\\n",
        encoding="utf-8",
    )
    metrics = parse_yolo_results_csv(results_csv)
    assert metrics["mAP50"] == 0.7
    assert metrics["mAP50_95"] == 0.4
    assert metrics["precision"] == 0.8
    assert metrics["recall"] == 0.6


def test_write_yolo_metrics_json_writes_full_metric_contract(tmp_path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, write_yolo_metrics_json

    results_csv = tmp_path / "results.csv"
    results_csv.write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\\n0.7,0.4,0.8,0.6\\n",
        encoding="utf-8",
    )
    metrics_path = tmp_path / "metrics.json"
    status_path = tmp_path / "status.json"
    write_yolo_metrics_json(
        results_csv=results_csv,
        metrics_path=metrics_path,
        status_path=status_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={"results_csv": "results.csv", "best_checkpoint": "weights/best.pt"},
            train_time_sec=123.4,
            infer_time_ms=7.8,
            peak_mem_mb=4096.0,
            param_count=20500000,
            checkpoint_size_mb=82.1,
        ),
    )
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert set(payload) >= {
        "benchmark_name",
        "split_manifest_hash",
        "model_name",
        "preset",
        "holdout_seed",
        "split_seed",
        "train_seed",
        "status",
        "mAP50_95",
        "mAP50",
        "precision",
        "recall",
        "f1",
        "train_time_sec",
        "infer_time_ms",
        "peak_mem_mb",
        "param_count",
        "checkpoint_size_mb",
        "artifact_paths",
    }
    assert payload["status"] == "succeeded"
    assert payload["mAP50"] == 0.7
    assert payload["mAP50_95"] == 0.4
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.6
    assert payload["f1"] == pytest.approx(2 * 0.8 * 0.6 / (0.8 + 0.6), abs=1e-6)
    assert payload["artifact_paths"]["best_checkpoint"] == "weights/best.pt"
    assert payload["checkpoint_size_mb"] == 82.1


def test_write_yolo_metrics_json_marks_failed_when_results_missing(tmp_path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, write_yolo_metrics_json

    metrics_path = tmp_path / "metrics.json"
    status_path = tmp_path / "status.json"
    write_yolo_metrics_json(
        results_csv=tmp_path / "missing.csv",
        metrics_path=metrics_path,
        status_path=status_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={"work_dir": "workdirs/yolo11m_obb/split-11/seed-101"},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
    )
    assert metrics_path.exists()
    assert status_path.exists()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["split_manifest_hash"] == "abc123"
    assert payload["model_name"] == "yolo11m_obb"
    assert payload["preset"] == "yolo11m-obb"
    assert payload["holdout_seed"] == 3407
    assert payload["split_seed"] == 11
    assert payload["train_seed"] == 101
    assert "artifact_paths" in payload
    assert payload["mAP50"] is None
    assert payload["mAP50_95"] is None
    assert payload["precision"] is None
    assert payload["recall"] is None
    assert payload["f1"] is None
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_runners_yolo.py -q
```

Expected:

```text
FAIL ... ModuleNotFoundError: No module named 'obb_baseline.runners_yolo'
```

- [ ] **Step 3: 实现 YOLO runner**

核心函数：

```python
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunMetadata:
    benchmark_name: str
    split_manifest_hash: str
    model_name: str
    preset: str
    holdout_seed: int
    split_seed: int
    train_seed: int
    artifact_paths: dict[str, str]
    train_time_sec: float | None
    infer_time_ms: float | None
    peak_mem_mb: float | None
    param_count: int | None
    checkpoint_size_mb: float | None


def build_yolo_train_command(
    *,
    preset: str,
    dataset_yaml: Path,
    run_dir: Path,
    work_dir: Path,
    train_seed: int,
    device: str,
    imgsz: int,
    epochs: int,
    batch_size: int,
) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
        "python",
        "-m",
        "ultralytics",
        "train",
        "task=obb",
        f"model={preset}",
        f"data={dataset_yaml}",
        f"project={work_dir.parent}",
        f"name={work_dir.name}",
        f"seed={train_seed}",
        f"device={device}",
        f"imgsz={imgsz}",
        f"epochs={epochs}",
        f"batch={batch_size}",
    ]


def parse_yolo_results_csv(results_csv: Path) -> dict[str, float | None]:
    row = load_last_csv_row(results_csv)
    return {
        "mAP50": row["metrics/mAP50(B)"],
        "mAP50_95": row["metrics/mAP50-95(B)"],
        "precision": row["metrics/precision(B)"],
        "recall": row["metrics/recall(B)"],
    }


def write_yolo_metrics_json(
    *,
    results_csv: Path,
    metrics_path: Path,
    status_path: Path,
    run_metadata: RunMetadata,
) -> None:
    if results_csv.exists():
        parsed = parse_yolo_results_csv(results_csv)
        status = "succeeded"
    else:
        parsed = {"mAP50": None, "mAP50_95": None, "precision": None, "recall": None}
        status = "failed"
    f1 = None
    if parsed["precision"] is not None and parsed["recall"] is not None and parsed["precision"] + parsed["recall"] != 0:
        f1 = 2 * parsed["precision"] * parsed["recall"] / (parsed["precision"] + parsed["recall"])
    payload = {
        "benchmark_name": run_metadata.benchmark_name,
        "split_manifest_hash": run_metadata.split_manifest_hash,
        "model_name": run_metadata.model_name,
        "preset": run_metadata.preset,
        "holdout_seed": run_metadata.holdout_seed,
        "split_seed": run_metadata.split_seed,
        "train_seed": run_metadata.train_seed,
        "status": status,
        "mAP50_95": parsed["mAP50_95"],
        "mAP50": parsed["mAP50"],
        "precision": parsed["precision"],
        "recall": parsed["recall"],
        "f1": f1,
        "train_time_sec": run_metadata.train_time_sec,
        "infer_time_ms": run_metadata.infer_time_ms,
        "peak_mem_mb": run_metadata.peak_mem_mb,
        "param_count": run_metadata.param_count,
        "checkpoint_size_mb": run_metadata.checkpoint_size_mb,
        "artifact_paths": run_metadata.artifact_paths,
    }
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    status_path.write_text(json.dumps({"status": status}), encoding="utf-8")
```

实现要求：

- runner 的边界固定为：
  - `build_yolo_train_command(...)` 只负责命令构造
  - `parse_yolo_results_csv(...)` 只负责解析原始结果
  - `write_yolo_metrics_json(...)` 只负责标准化输出
- `RunMetadata` 必须把 spec 10.4 的 run 级元数据一次性传齐，避免在 writer 内部猜字段来源
- 子进程入口固定为 yolo 环境
- 不在父进程 import `ultralytics`
- 子进程必须能解析到 `obb_baseline` 包；优先由 `run_suite.py` 在 `subprocess.run(..., env=...)` 中注入 `PYTHONPATH=benchmarks/obb_baseline/src`
- 训练命令必须显式带上 `preset`、`dataset_yaml`、`work_dir` 映射、`train_seed`、`device`、`imgsz`、`epochs`、`batch_size`
- 若 `results.csv` 缺失则写失败状态到 `status.json`
- `metrics.json` 必须完整写出 spec 10.4 的标准键；失败 run 的核心精度字段也必须存在，但值写成 `null`

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_runners_yolo.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/src/obb_baseline/runners_yolo.py benchmarks/obb_baseline/tests/test_runners_yolo.py
git commit -m "feat: add yolo benchmark runner"
```

### Task 9: 实现 `runners_mmrotate.py`

**Files:**
- Create: `benchmarks/obb_baseline/src/obb_baseline/runners_mmrotate.py`
- Create: `benchmarks/obb_baseline/tests/test_runners_mmrotate.py`

- [ ] **Step 1: 写 MMRotate runner 失败测试**

```python
import json
import pytest


def test_build_mmrotate_command_uses_mmrotate_env(tmp_path) -> None:
    from obb_baseline.runners_mmrotate import build_mmrotate_train_command

    command = build_mmrotate_train_command(
        model_name="oriented_rcnn_r50",
        generated_config=tmp_path / "config.py",
        run_dir=tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101",
        work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
        train_seed=101,
        device="0",
    )
    assert command[:4] == [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/mmrotate",
    ]
    assert command[4:7] == ["python", "-m", "obb_baseline.runners_mmrotate"]
    assert "--config" in command
    assert str(tmp_path / "config.py") in command
    assert "--work-dir" in command
    assert str(tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101") in command
    assert "--seed" in command
    assert "101" in command
    assert "--device" in command
    assert "0" in command


def test_render_mmrotate_config_supports_all_four_presets(tmp_path) -> None:
    from obb_baseline.runners_mmrotate import render_mmrotate_config

    expected_markers = {
        "oriented_rcnn_r50": "oriented_rcnn",
        "roi_transformer_r50": "roi_transformer",
        "r3det_r50": "r3det",
        "rtmdet_rotated_m": "rtmdet_rotated",
    }
    for model_name, marker in expected_markers.items():
        rendered = render_mmrotate_config(
            model_name=model_name,
            data_root=tmp_path / "views" / "split-11" / "dota",
            classes=("pattern_a", "pattern_b", "pattern_c"),
            work_dir=tmp_path / "workdirs" / model_name,
            train_seed=101,
            score_thr=0.05,
        )
        assert f'base_preset = "{marker}"' in rendered
        assert str(tmp_path / "views" / "split-11" / "dota") in rendered
        assert str(tmp_path / "workdirs" / model_name) in rendered
        assert "train_seed = 101" in rendered
        assert "score_thr = 0.05" in rendered
        assert "class_names" in rendered
        assert "num_classes=3" in rendered or "num_classes = 3" in rendered


def test_normalize_mmrotate_metrics_returns_full_metric_contract() -> None:
    from obb_baseline.runners_mmrotate import normalize_mmrotate_metrics

    metrics = normalize_mmrotate_metrics(
        {
            "dota/AP50": 0.71,
            "dota/mAP": 0.42,
            "precision": 0.8,
            "recall": 0.65,
        }
    )
    assert metrics["mAP50"] == 0.71
    assert metrics["mAP50_95"] == 0.42
    assert metrics["precision"] == 0.8
    assert metrics["recall"] == 0.65
    assert metrics["f1"] == pytest.approx(2 * 0.8 * 0.65 / (0.8 + 0.65), abs=1e-6)


def test_write_mmrotate_metrics_json_preserves_full_metric_contract(tmp_path) -> None:
    from obb_baseline.runners_mmrotate import RunMetadata, write_mmrotate_metrics_json

    metrics_path = tmp_path / "metrics.json"
    write_mmrotate_metrics_json(
        normalized_metrics={"mAP50": 0.71, "mAP50_95": 0.42, "precision": 0.8, "recall": 0.65, "f1": 0.7172413793},
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="oriented_rcnn_r50",
            preset="oriented-rcnn-r50-fpn",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={"best_checkpoint": "best.pth"},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        status="succeeded",
    )
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert set(payload) >= {
        "benchmark_name",
        "split_manifest_hash",
        "model_name",
        "preset",
        "holdout_seed",
        "split_seed",
        "train_seed",
        "status",
        "mAP50_95",
        "mAP50",
        "precision",
        "recall",
        "f1",
        "train_time_sec",
        "infer_time_ms",
        "peak_mem_mb",
        "param_count",
        "checkpoint_size_mb",
        "artifact_paths",
    }
    assert payload["status"] == "succeeded"
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["split_manifest_hash"] == "abc123"
    assert payload["model_name"] == "oriented_rcnn_r50"
    assert payload["preset"] == "oriented-rcnn-r50-fpn"
    assert payload["holdout_seed"] == 3407
    assert payload["split_seed"] == 11
    assert payload["train_seed"] == 101
    assert payload["mAP50"] == 0.71
    assert payload["mAP50_95"] == 0.42
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.65
    assert payload["f1"] == pytest.approx(0.7172413793, abs=1e-6)
    assert payload["artifact_paths"]["best_checkpoint"] == "best.pth"
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_runners_mmrotate.py -q
```

Expected:

```text
FAIL ... ModuleNotFoundError: No module named 'obb_baseline.runners_mmrotate'
```

- [ ] **Step 3: 实现 MMRotate runner**

实现要求：

```python
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunMetadata:
    benchmark_name: str
    split_manifest_hash: str
    model_name: str
    preset: str
    holdout_seed: int
    split_seed: int
    train_seed: int
    artifact_paths: dict[str, str]
    train_time_sec: float | None
    infer_time_ms: float | None
    peak_mem_mb: float | None
    param_count: int | None
    checkpoint_size_mb: float | None


def render_mmrotate_config(
    *,
    model_name: str,
    data_root: Path,
    classes: tuple[str, ...],
    work_dir: Path,
    train_seed: int,
    score_thr: float,
) -> str:
    preset_markers = {
        "oriented_rcnn_r50": "oriented_rcnn",
        "roi_transformer_r50": "roi_transformer",
        "r3det_r50": "r3det",
        "rtmdet_rotated_m": "rtmdet_rotated",
    }
    marker = preset_markers[model_name]
    return (
        f'base_preset = "{marker}"\\n'
        f"data_root = {str(data_root)!r}\\n"
        f"class_names = {classes!r}\\n"
        f"num_classes = {len(classes)}\\n"
        f"work_dir = {str(work_dir)!r}\\n"
        f"train_seed = {train_seed}\\n"
        f"score_thr = {score_thr}\\n"
    )


def build_mmrotate_train_command(
    *,
    model_name: str,
    generated_config: Path,
    run_dir: Path,
    work_dir: Path,
    train_seed: int,
    device: str,
) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/mmrotate",
        "python",
        "-m",
        "obb_baseline.runners_mmrotate",
        "--config",
        str(generated_config),
        "--work-dir",
        str(work_dir),
        "--seed",
        str(train_seed),
        "--device",
        str(device),
    ]


def normalize_mmrotate_metrics(raw_metrics: dict[str, object]) -> dict[str, float | None]:
    precision = raw_metrics.get("precision")
    recall = raw_metrics.get("recall")
    f1 = None
    if precision is not None and recall is not None and precision + recall != 0:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "mAP50": raw_metrics.get("dota/AP50"),
        "mAP50_95": raw_metrics.get("dota/mAP"),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def write_mmrotate_metrics_json(
    *,
    normalized_metrics: dict[str, float | None],
    metrics_path: Path,
    run_metadata: RunMetadata,
    status: str,
) -> None:
    payload = {
        "benchmark_name": run_metadata.benchmark_name,
        "split_manifest_hash": run_metadata.split_manifest_hash,
        "model_name": run_metadata.model_name,
        "preset": run_metadata.preset,
        "holdout_seed": run_metadata.holdout_seed,
        "split_seed": run_metadata.split_seed,
        "train_seed": run_metadata.train_seed,
        "status": status,
        "mAP50_95": normalized_metrics["mAP50_95"],
        "mAP50": normalized_metrics["mAP50"],
        "precision": normalized_metrics["precision"],
        "recall": normalized_metrics["recall"],
        "f1": normalized_metrics["f1"],
        "train_time_sec": run_metadata.train_time_sec,
        "infer_time_ms": run_metadata.infer_time_ms,
        "peak_mem_mb": run_metadata.peak_mem_mb,
        "param_count": run_metadata.param_count,
        "checkpoint_size_mb": run_metadata.checkpoint_size_mb,
        "artifact_paths": run_metadata.artifact_paths,
    }
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
```

必须做到：

- runner 的边界固定为：
  - `render_mmrotate_config(...)` 只负责配置渲染
  - `build_mmrotate_train_command(...)` 只负责命令构造
  - `normalize_mmrotate_metrics(...)` / `write_mmrotate_metrics_json(...)` 只负责结果标准化
- `RunMetadata` 必须显式承载 spec 10.4 的 run 级元数据，writer 不能隐式依赖外部状态
- 4 个模型共用一个 runner 文件，但 preset 分支清晰
- 父进程只做配置渲染和命令构造
- 真正的 MMRotate 执行通过 `uv run --project ... python -m obb_baseline.runners_mmrotate ...` 子进程完成
- 子进程必须能解析到 `obb_baseline` 包；优先由 `run_suite.py` 在 `subprocess.run(..., env=...)` 中注入 `PYTHONPATH=benchmarks/obb_baseline/src`
- `metrics.json` 必须完整写出 spec 10.4 的标准键；工程补充字段允许写 `null`，但键不能缺
- 训练命令必须显式带上 `generated_config`、`work_dir`、`train_seed` 和 `device`，不能只返回环境前缀
- `render_mmrotate_config(...)` 必须把 4 个 `model_name` 显式映射到不同的 preset/base marker，并且渲染结果必须包含 `data_root`、`work_dir`、`train_seed`、`score_thr`、`class_names`、`num_classes`
- 配置里动态注入：
  - `classes`
  - `num_classes`
  - `data_root`
  - `work_dir`
  - `train_seed`
  - `score_thr`

可直接借鉴但不要直接 import 现有插件里的实现思路：

- [config_builder.py](/Users/hhm/code/saki/.worktrees/paper-obb-benchmark/saki-plugins/saki-plugin-oriented-rcnn/src/saki_plugin_oriented_rcnn/config_builder.py)
- [metrics_service.py](/Users/hhm/code/saki/.worktrees/paper-obb-benchmark/saki-plugins/saki-plugin-oriented-rcnn/src/saki_plugin_oriented_rcnn/metrics_service.py)

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_runners_mmrotate.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/src/obb_baseline/runners_mmrotate.py benchmarks/obb_baseline/tests/test_runners_mmrotate.py
git commit -m "feat: add mmrotate benchmark runner"
```

### Task 10: 实现 `run_suite.py`

**Files:**
- Modify: `benchmarks/obb_baseline/scripts/run_suite.py`
- Create: `benchmarks/obb_baseline/tests/test_run_suite.py`

- [ ] **Step 1: 写 suite 失败测试**

```python
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def load_run_suite_module():
    spec = importlib.util.spec_from_file_location(
        "obb_run_suite",
        Path("benchmarks/obb_baseline/scripts/run_suite.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def create_stub_metrics(benchmark_root: Path) -> None:
    run_dir = benchmark_root / "records" / "yolo11m_obb" / "split-11" / "seed-101"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(
        '{"status":"succeeded","model_name":"yolo11m_obb","split_seed":11,"train_seed":101,"mAP50_95":0.40,"mAP50":0.70,"precision":0.8,"recall":0.6,"f1":0.6857}',
        encoding="utf-8",
    )


def write_split_manifest(path: Path, *, split_seeds: list[int], test_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset_name": "tiny_dota_export",
        "holdout_seed": 3407,
        "test_ratio": 0.15,
        "val_ratio": 0.15,
        "split_seeds": split_seeds,
        "splits": {
            str(seed): {
                "train_ids": ["img_001", "img_002"],
                "val_ids": ["img_003"],
                "test_ids": test_ids,
            }
            for seed in split_seeds
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "benchmark_name: fedo_part2_v1\\nmodels: [yolo11m_obb, oriented_rcnn_r50]\\nruntime:\\n  device: '0'\\n",
        encoding="utf-8",
    )


def test_run_suite_skips_completed_runs_and_regenerates_summary(tmp_path, monkeypatch) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    write_config(benchmark_root / "config.yaml")
    records_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    records_dir.mkdir(parents=True, exist_ok=True)
    (records_dir / "metrics.json").write_text('{"status":"succeeded","model_name":"oriented_rcnn_r50","split_seed":11,"train_seed":101,"mAP50_95":0.44,"mAP50":0.61,"precision":0.7,"recall":0.6,"f1":0.6462}', encoding="utf-8")

    dispatch_calls: list[dict[str, object]] = []

    def fail_dispatch(**kwargs):
        dispatch_calls.append(kwargs)
        raise AssertionError("completed run should be skipped")

    monkeypatch.setattr(module, "dispatch_runner", fail_dispatch)
    monkeypatch.setattr(module, "execute_launch", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("execute_launch should not be called")))
    monkeypatch.setattr(module, "parse_and_write_outputs", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("parse_and_write_outputs should not be called")))

    result = module.main(
        [
            "--config",
            str(benchmark_root / "config.yaml"),
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
    assert result == 0
    assert dispatch_calls == []
    assert (benchmark_root / "config.snapshot.yaml").exists()
    assert (benchmark_root / "leaderboard.csv").exists()


def test_run_suite_reruns_failed_run_when_flag_is_present(tmp_path, monkeypatch) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    write_config(benchmark_root / "config.yaml")
    failed_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
    failed_dir.mkdir(parents=True, exist_ok=True)
    (failed_dir / "metrics.json").write_text('{"status":"failed","model_name":"oriented_rcnn_r50","split_seed":11,"train_seed":101}', encoding="utf-8")

    dispatch_calls: list[dict[str, object]] = []
    execute_calls: list[tuple[object, object]] = []
    parse_calls: list[dict[str, object]] = []

    def dispatch_runner(**kwargs):
        dispatch_calls.append(kwargs)
        return SimpleNamespace(command=["echo", "ok"], cwd=str(benchmark_root), extra_env={})

    def execute_launch(launch, env):
        execute_calls.append((launch, env))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    def parse_and_write_outputs(**kwargs):
        parse_calls.append(kwargs)
        run_dir = benchmark_root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "metrics.json").write_text(
            '{"status":"succeeded","model_name":"oriented_rcnn_r50","split_seed":11,"train_seed":101,"mAP50_95":0.44,"mAP50":0.61,"precision":0.7,"recall":0.6,"f1":0.6462}',
            encoding="utf-8",
        )

    monkeypatch.setattr(module, "dispatch_runner", dispatch_runner)
    monkeypatch.setattr(module, "execute_launch", execute_launch)
    monkeypatch.setattr(module, "parse_and_write_outputs", parse_and_write_outputs)

    result = module.main(
        [
            "--config",
            str(benchmark_root / "config.yaml"),
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
    assert result == 0
    assert len(dispatch_calls) == 1
    assert len(execute_calls) == 1
    assert len(parse_calls) == 1


def test_run_suite_writes_standard_run_artifacts(tmp_path, monkeypatch) -> None:
    module = load_run_suite_module()
    benchmark_root = tmp_path / "runs" / "obb_baseline" / "fedo_part2_v1"
    write_split_manifest(benchmark_root / "split_manifest.json", split_seeds=[11], test_ids=["img_004"])
    write_config(benchmark_root / "config.yaml")

    monkeypatch.setattr(
        module,
        "dispatch_runner",
        lambda **_kwargs: SimpleNamespace(command=["echo", "ok"], cwd=str(benchmark_root), extra_env={}),
    )
    monkeypatch.setattr(
        module,
        "execute_launch",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="train ok\n", stderr=""),
    )
    monkeypatch.setattr(module, "parse_and_write_outputs", lambda *_args, **_kwargs: create_stub_metrics(benchmark_root))

    result = module.main(
        [
            "--config",
            str(benchmark_root / "config.yaml"),
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
    assert result == 0
    run_dir = benchmark_root / "records" / "yolo11m_obb" / "split-11" / "seed-101"
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "run_config.json").exists()
    assert (run_dir / "status.json").exists()
    assert (run_dir / "stdout.log").exists()
    assert (run_dir / "stderr.log").exists()
    assert json.loads((run_dir / "status.json").read_text(encoding="utf-8"))["status"] == "succeeded"
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_run_suite.py -q
```

Expected:

```text
FAIL ... run_suite.py exited with non-zero status
```

- [ ] **Step 3: 实现 suite CLI**

核心流程固定为：

```python
def main() -> int:
    args = parse_args()
    benchmark_root = Path(args.benchmark_root).resolve()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    manifest = json.loads((benchmark_root / "split_manifest.json").read_text(encoding="utf-8"))
    registry = load_model_registry(Path("benchmarks/obb_baseline/configs/models.yaml"))
    child_env = build_child_env(pythonpath="benchmarks/obb_baseline/src")
    write_config_snapshot(benchmark_root / "config.snapshot.yaml", config)
    for model_name in selected_models:
        for split_seed in selected_split_seeds:
            ensure_view_materialized(benchmark_root=benchmark_root, model_name=model_name, split_seed=split_seed, manifest=manifest, config=config)
            for train_seed in selected_train_seeds:
                if should_skip_run(benchmark_root=benchmark_root, model_name=model_name, split_seed=split_seed, train_seed=train_seed):
                    continue
                run_dir = resolve_run_dir(benchmark_root, model_name, split_seed, train_seed)
                launch = dispatch_runner(model_name=model_name, split_seed=split_seed, train_seed=train_seed, benchmark_root=benchmark_root, config=config, manifest=manifest, registry=registry)
                write_run_config(run_dir, launch, config, manifest)
                result = execute_launch(launch, env=child_env)
                write_status_and_logs(run_dir, result)
                parse_and_write_outputs(model_name=model_name, split_seed=split_seed, train_seed=train_seed, benchmark_root=benchmark_root, registry=registry)
    outputs = collect_suite_outputs(benchmark_name=config["benchmark_name"], benchmark_root=benchmark_root)
    write_suite_outputs(outputs, benchmark_root)
    return 0
```

实现要求：

- `run_suite.py` 的职责固定为：
  - 读取配置和 manifest
  - 物化视图
  - 写 `config.snapshot.yaml`
  - 写 `run_config.json`
  - 执行子进程并根据执行结果写 `stdout.log` / `stderr.log`
  - 根据执行结果写 `status.json`
  - 调用 runner 的解析函数
  - 最后统一写 suite 汇总
- runner 与 suite 的接口边界固定为：
  - runner 返回 `RunnerLaunch(command, cwd, extra_env)`
  - suite 负责真正执行 `subprocess.run`，并把 `returncode/stdout/stderr` 落成标准记录文件
  - runner 负责解析原始框架输出并写标准 `metrics.json`
- 只在 suite 末尾统一重写三份汇总文件
- 默认从 `<benchmark_root>/split_manifest.json` 读取切分结果；若文件缺失则直接失败
- 成功 run 的跳过条件是 `metrics.json` 存在且 `status == "succeeded"`
- 失败 run 需要保留 `stdout.log`、`stderr.log`、`status.json`
- `run_config.json` 要把本次运行的全部关键参数固化下来
- `dispatch_runner`、`execute_launch`、`parse_and_write_outputs` 的测试必须显式断言调用次数，确保“成功 run 跳过、失败 run 重跑”的行为被锁住

CLI 参数至少包含：

- `--config`
- `--benchmark-root`
- `--models`
- `--split-seeds`
- `--train-seeds`
- `--rerun-failed`

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_run_suite.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/scripts/run_suite.py benchmarks/obb_baseline/tests/test_run_suite.py
git commit -m "feat: add benchmark suite runner"
```

## Chunk 4: Docs And Verification

### Task 11: 补全 README 与默认配置

**Files:**
- Modify: `benchmarks/obb_baseline/README.md`
- Modify: `benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml`
- Modify: `benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml`
- Create: `benchmarks/obb_baseline/tests/test_configs.py`

- [ ] **Step 1: 写配置与 README 完整性测试**

```python
from pathlib import Path

import yaml


def test_benchmark_configs_contain_required_keys() -> None:
    payload = yaml.safe_load(Path("benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml").read_text(encoding="utf-8"))
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["dataset"]["dota_root"]
    assert payload["dataset"]["yolo_obb_root"]
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
    assert payload["dataset"]["dota_root"]
    assert payload["dataset"]["yolo_obb_root"]
    assert payload["dataset"]["classes"] == ["pattern_a", "pattern_b", "pattern_c"]
    assert payload["models"] == ["oriented_rcnn_r50"]
    assert "split_manifest_path" in payload
    assert isinstance(payload["split_manifest_path"], str)
    assert payload["runtime"]["device"] == "0"
    assert payload["runtime"]["score_thr"] == 0.05
    assert payload["runtime"]["link_mode"] == "symlink"


def test_readme_mentions_required_commands_and_artifacts() -> None:
    text = Path("benchmarks/obb_baseline/README.md").read_text(encoding="utf-8")
    assert "uv sync --project benchmarks/obb_baseline/envs/mmrotate" in text
    assert "uv sync --project benchmarks/obb_baseline/envs/yolo" in text
    assert "split_dataset.py" in text
    assert "run_suite.py" in text
    assert "Stage 0 smoke" in text
    assert "summary.csv" in text
    assert "leaderboard.csv" in text
    assert "summary.md" in text
    assert "runs/obb_baseline/<benchmark_name>/" in text
    assert "默认配置是模板" in text
    assert "benchmark.smoke.local.yaml" in text
```

- [ ] **Step 2: 跑测试并确认失败**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_configs.py -q
```

Expected:

```text
FAIL ... KeyError: 'benchmark_name'
```

- [ ] **Step 3: 补全 README 与配置模板**

`benchmark.fedo_part2_v1.yaml` 至少包含：

```yaml
benchmark_name: fedo_part2_v1
dataset:
  dota_root: "__SET_ME__/dota_export"
  yolo_obb_root: "__SET_ME__/yolo_obb_export"
  classes: [pattern_a, pattern_b, pattern_c]
splits:
  holdout_seed: 3407
  split_seeds: [11, 17, 23]
  train_seeds: [101, 202, 303]
  test_ratio: 0.15
  val_ratio: 0.15
models:
  - yolo11m_obb
  - oriented_rcnn_r50
  - roi_transformer_r50
  - r3det_r50
  - rtmdet_rotated_m
runtime:
  device: "0"
  score_thr: 0.05
  link_mode: symlink
```

`benchmark.fedo_part3_orcnn_v1.yaml` 至少包含：

```yaml
benchmark_name: fedo_part3_orcnn_v1
split_manifest_path: ""
dataset:
  dota_root: "__SET_ME__/dota_export"
  yolo_obb_root: "__SET_ME__/yolo_obb_export"
  classes: [pattern_a, pattern_b, pattern_c]
models:
  - oriented_rcnn_r50
runtime:
  device: "0"
  score_thr: 0.05
  link_mode: symlink
```

README 必须包含：

- 两个环境的 `uv sync` 命令
- `split_dataset.py` 示例命令
- `run_suite.py` 示例命令
- Stage 0 smoke 示例命令
- 运行产物目录说明，至少明确 `runs/obb_baseline/<benchmark_name>/`、`summary.csv`、`leaderboard.csv`、`summary.md`
- 仓库内默认配置是模板；Stage 0 smoke 需要在 `runs/` 下生成本地可执行配置，不直接改仓库模板

- [ ] **Step 4: 跑测试并确认通过**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests/test_configs.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: 提交**

```bash
git add benchmarks/obb_baseline/README.md benchmarks/obb_baseline/configs benchmarks/obb_baseline/tests/test_configs.py
git commit -m "docs: add benchmark usage and configs"
```

### Task 12: 做完整验证并记录 Stage 0 smoke 步骤

**Files:**
- Modify: `benchmarks/obb_baseline/README.md`

- [ ] **Step 1: 跑全部单测**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pytest --with pyyaml pytest benchmarks/obb_baseline/tests -q
```

Expected:

```text
32 passed
```

- [ ] **Step 2: 生成两个环境**

Run:

```bash
uv sync --project benchmarks/obb_baseline/envs/mmrotate
uv sync --project benchmarks/obb_baseline/envs/yolo
```

Expected:

```text
both commands exit 0 and create `benchmarks/obb_baseline/envs/mmrotate/.venv` and `benchmarks/obb_baseline/envs/yolo/.venv`
```

- [ ] **Step 3: 跑 Stage 0 smoke 的切分**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml python benchmarks/obb_baseline/scripts/split_dataset.py \
  --dota-root /path/to/dota_export \
  --classes pattern_a,pattern_b,pattern_c \
  --out-dir runs/obb_baseline/fedo_part2_smoke \
  --holdout-seed 3407 \
  --split-seeds 11
```

Expected:

```text
split_manifest.json and split_summary.json written
```

- [ ] **Step 4: 由模板生成本地 smoke 配置**

Run:

```bash
env DOTA_ROOT=/path/to/dota_export \
    YOLO_OBB_ROOT=/path/to/yolo_obb_export \
    SMOKE_ROOT=runs/obb_baseline/fedo_part2_smoke \
    uv run --with pyyaml python - <<'PY'
import os
from pathlib import Path
import yaml

template = yaml.safe_load(Path("benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml").read_text(encoding="utf-8"))
template["benchmark_name"] = "fedo_part2_smoke"
template["dataset"]["dota_root"] = os.environ["DOTA_ROOT"]
template["dataset"]["yolo_obb_root"] = os.environ["YOLO_OBB_ROOT"]
template["models"] = ["yolo11m_obb", "oriented_rcnn_r50"]
template["splits"]["split_seeds"] = [11]
template["splits"]["train_seeds"] = [101]
smoke_root = Path(os.environ["SMOKE_ROOT"])
smoke_root.mkdir(parents=True, exist_ok=True)
(smoke_root / "benchmark.smoke.local.yaml").write_text(
    yaml.safe_dump(template, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
PY
```

Expected:

```text
`runs/obb_baseline/fedo_part2_smoke/benchmark.smoke.local.yaml` exists and its `benchmark_name` is `fedo_part2_smoke`
```

- [ ] **Step 5: 跑 Stage 0 smoke 的 suite**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml python benchmarks/obb_baseline/scripts/run_suite.py \
  --config runs/obb_baseline/fedo_part2_smoke/benchmark.smoke.local.yaml \
  --benchmark-root runs/obb_baseline/fedo_part2_smoke \
  --models yolo11m_obb,oriented_rcnn_r50 \
  --split-seeds 11 \
  --train-seeds 101
```

Expected:

```text
suite exits 0 and writes Stage 0 run artifacts under `runs/obb_baseline/fedo_part2_smoke/records/`
```

- [ ] **Step 6: 验证 Stage 0 smoke 的统一产物契约**

Run:

```bash
env PYTHONPATH=benchmarks/obb_baseline/src uv run --with pyyaml python - <<'PY'
import json
from pathlib import Path

root = Path("runs/obb_baseline/fedo_part2_smoke")
yolo_metrics = json.loads((root / "records" / "yolo11m_obb" / "split-11" / "seed-101" / "metrics.json").read_text(encoding="utf-8"))
mmrotate_metrics = json.loads((root / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101" / "metrics.json").read_text(encoding="utf-8"))
required = {
    "benchmark_name",
    "split_manifest_hash",
    "model_name",
    "preset",
    "holdout_seed",
    "split_seed",
    "train_seed",
    "status",
    "mAP50_95",
    "mAP50",
    "precision",
    "recall",
    "f1",
    "train_time_sec",
    "infer_time_ms",
    "peak_mem_mb",
    "param_count",
    "checkpoint_size_mb",
    "artifact_paths",
}
assert required.issubset(yolo_metrics)
assert required.issubset(mmrotate_metrics)
assert (root / "summary.csv").exists()
assert (root / "leaderboard.csv").exists()
assert (root / "summary.md").exists()
print("stage0-smoke-verified")
PY
```

Expected:

```text
stage0-smoke-verified
```

- [ ] **Step 7: 最终提交**

```bash
git add benchmarks/obb_baseline
git commit -m "feat: complete obb benchmark phase1"
```

## Notes For Implementers

- 优先保证 Phase 1 最小闭环，不要提前拆 `materialize_splits.py` 或 `collect_results.py`。
- 先做 unit test，再做最小实现，不要反过来。
- 任何会 import 重框架的逻辑都必须位于子进程边界之后。
- 若 MMRotate 的配置渲染开始膨胀，不要把多模型分支硬塞进一个巨大字符串里；可以先在 `runners_mmrotate.py` 内拆多个小模板函数，但不要新增对外脚本。
- 若某个工程补充指标短时间内无法稳定采集，先写 `null`，不要阻塞 Phase 1。
