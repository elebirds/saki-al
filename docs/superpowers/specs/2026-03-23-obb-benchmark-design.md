# 论文 OBB 基线 Benchmark 设计说明

日期：2026-03-23

## 1. 定位

本文档定义一套面向论文实验的 OBB benchmark harness，用于在 Saki 现有数据导出能力之上，完成以下链路：

- 从导出后的全集自动切分 `train/val/test`
- 按统一 split 批量运行多种 OBB 检测模型
- 采集统一口径的结果
- 输出可直接进入论文的汇总表

该设计服务于论文的两部分实验：

- 第二部分：卫星电子图谱数据集上的代表性 OBB 基线模型对比
- 第三部分：基于 `Oriented R-CNN` 的方法改进实验

这套代码不进入 Saki 主线插件体系，而是在仓库中新增独立目录维护。

## 2. 范围与非目标

### 2.1 范围

第一版只处理导出数据集之后的链路：

- 数据切分
- 数据视图投影
- 批量训练与评测调度
- 结果标准化与汇总

### 2.2 非目标

以下内容不属于第一版范围：

- 不接管 Saki 的标注、导入、导出逻辑
- 不把这些基线模型重新做成 Saki 插件
- 不支持 HBB，只支持 OBB
- 不做自动调参或超参数搜索
- 不做多机多卡调度
- 不做 Web 面板
- 不做统一 evaluator 重评分

## 3. 研究问题与比较口径

### 3.1 第二部分实验问题

第二部分不是回答“哪个模型综合最优”，而是回答：

- 在卫星电子图谱 OBB 细长目标场景下，代表性 OBB 检测范式的精度表现如何
- 在多 split、多 train seed 条件下，不同模型的稳定性如何

第二部分主排序指标固定为 `mAP50_95`。

### 3.2 第三部分实验问题

第三部分单独以 `Oriented R-CNN` 作为改进基线。

第三部分不要求绑定第二部分中精度最高的模型，但必须复用：

- 同一份数据切分协议
- 同一份冻结的 `split_manifest`
- 同一套运行产物规范
- 同一套汇总口径

## 4. 模型矩阵

第一版固定比较以下 5 个模型：

1. `YOLO11m-OBB`
2. `Oriented R-CNN` R50-FPN
3. `RoI Transformer` R50-FPN
4. `R3Det` R50-FPN
5. `RTMDet-Rotated` medium

选择理由如下：

- `YOLO11m-OBB`
  - 代表工业上常见的一阶段 OBB 基线
- `Oriented R-CNN`
  - 代表两阶段 RoI 系方法
  - 同时也是第三部分改进实验的承载基线
- `RoI Transformer`
  - 代表早期经典的旋转 RoI 几何变换路线
- `R3Det`
  - 代表一阶段渐进 refinement 路线
- `RTMDet-Rotated`
  - 代表较新的现代一阶段旋转检测基线

设计原则：

- 每个模型只保留一个代表性 preset
- 第二部分比较的是“检测范式”，不是“同模型不同尺寸变体”

## 5. 数据前提与切分协议

### 5.1 输入前提

第一版假设用户已经从 Saki 导出好数据集。

benchmark harness 只要求以下输入：

- 一个用于切分与 MMRotate 训练的 `DOTA` 导出根目录
- 一个用于 YOLO 训练的 `YOLO OBB` 导出根目录

约束如下：

- 同一样本在不同导出格式中的文件 stem 必须一致
- `DOTA` 导出作为切分时的唯一真值来源
- `YOLO OBB` 只在运行 YOLO 模型时按 stem 对齐校验

如果 stem 不一致，第一版直接 `fail fast`。

### 5.2 当前数据特点

当前任务已知特点：

- 图像规模约 3000 张
- `pattern` 共 3 类
- 负样本占比约 70% 至 80%
- 全任务为 OBB 检测
- 目标细长

因此切分必须显式控制负样本比例和类别共现，而不能做简单纯随机。

### 5.3 三层随机性

随机性拆为三层：

- `holdout_seed`
  - 只负责从全集中一次性切出固定 `test`
- `split_seed`
  - 只负责从剩余 `trainval` 中切出 `train/val`
- `train_seed`
  - 只负责训练初始化、DataLoader 随机性和框架侧训练扰动

实验单元定义为：

`(model, holdout_seed 固定, split_seed = i, train_seed = j)`

### 5.4 默认切分参数

默认参数固定为：

- `test_ratio = 0.15`
- `val_ratio = 0.15`
- `holdout_seed = 3407`
- `split_seeds = [11, 17, 23]`
- `train_seeds = [101, 202, 303]`

解释如下：

- `test_ratio = 0.15` 表示 `test` 占全集 15%
- `val_ratio = 0.15` 表示 `val` 也按全集语义占 15%
- 因此在 `trainval` 内部切分时，实际采用：
  - `val_within_trainval_ratio = 0.15 / (1 - 0.15) = 0.1764705882`

标准实验规模为：

- `3 个 split_seed × 3 个 train_seed = 9 runs / 模型`

### 5.5 分层策略

第一版采用轻量但明确的分层。

主分层键为：

1. `is_negative`
2. `class_mask`
3. `instance_count_bucket`

字段定义如下：

- `is_negative`
  - 图像中没有任何正样本时为 `true`
- `class_mask`
  - 3 类 pattern 的出现位图
- `instance_count_bucket`
  - `0`
  - `1`
  - `2-4`
  - `>=5`

为避免小 strata 导致切分失败，采用三级回退：

1. 先尝试 `(is_negative, class_mask, instance_count_bucket)`
2. 若某 strata 样本数小于 `3`，则该 strata 回退到 `(is_negative, class_mask)`
3. 若仍小于 `3`，继续回退到 `(is_negative)`

这个规则的目标不是做最优分层，而是稳定压住以下偏差：

- 负样本比例偏差
- 某类 pattern 在单个 split 中极端稀疏
- 某个 split 因样本密度更幸运而虚高

## 6. 工程架构

### 6.1 总体思路

第一版明确采用“小外部脚本 + 内部模块”的结构。

对外只保留两个 CLI 入口：

- `split_dataset.py`
- `run_suite.py`

其余能力全部放入内部模块，不在第一版额外暴露新脚本。

### 6.2 进程边界

第一版必须明确区分三类进程：

1. orchestration 进程
2. MMRotate 训练/测试进程
3. YOLO 训练/测试进程

约束如下：

- `split_dataset.py` 和 `run_suite.py` 属于 orchestration 层
- orchestration 层只负责：
  - 读取配置
  - 构造 split
  - 物化数据视图
  - 组织命令
  - 调用子进程
  - 解析结果
- orchestration 层不得在同一 Python 解释器中 import：
  - `onedl-mmrotate`
  - `onedl-mmcv`
  - `onedl-mmdetection`
  - `ultralytics`

换句话说，第一版不做“单解释器内多框架共存”。

### 6.3 内部模块

建议内部模块如下：

```text
benchmarks/obb_baseline/src/obb_baseline/
  splitters.py
  dataset_views.py
  registry.py
  runners_mmrotate.py
  runners_yolo.py
  summary.py
```

职责如下：

- `splitters.py`
  - 切分协议
  - 分层回退逻辑
  - `split_manifest.json` 与 `split_summary.json` 生成
- `dataset_views.py`
  - 根据样本 ID / stem 构建 `DOTA` 与 `YOLO OBB` 数据视图
- `registry.py`
  - 模型注册表
  - 模型与 runner、环境、默认 preset、数据视图的映射
- `runners_mmrotate.py`
  - `Oriented R-CNN`
  - `RoI Transformer`
  - `R3Det`
  - `RTMDet-Rotated`
- `runners_yolo.py`
  - `YOLO11m-OBB`
- `summary.py`
  - 汇总 `metrics.json`
  - 生成 `summary.csv`、`leaderboard.csv`、`summary.md`

## 7. 目录结构

### 7.1 代码目录

新增目录：

```text
benchmarks/obb_baseline/
  README.md
  configs/
    benchmark.fedo_part2_v1.yaml
    benchmark.fedo_part3_orcnn_v1.yaml
    models.yaml
  envs/
    mmrotate/
      pyproject.toml
      uv.lock
    yolo/
      pyproject.toml
      uv.lock
  scripts/
    split_dataset.py
    run_suite.py
  src/obb_baseline/
    splitters.py
    dataset_views.py
    registry.py
    runners_mmrotate.py
    runners_yolo.py
    summary.py
```

说明：

- `configs/` 只放 benchmark 配置和模型矩阵配置
- `envs/` 明确拆成两个 `uv` 项目
- 第一版不单独提供 `materialize_splits.py`
- 第一版不单独提供 `collect_results.py`

### 7.2 运行产物目录

运行产物统一落在：

```text
runs/obb_baseline/<benchmark_name>/
  split_manifest.json
  split_summary.json
  config.snapshot.yaml
  views/
    split-<split_seed>/
      dota/
      yolo_obb/
  workdirs/
    <model_name>/
      split-<split_seed>/
        seed-<train_seed>/
  records/
    <model_name>/
      split-<split_seed>/
        seed-<train_seed>/
          run_config.json
          status.json
          stdout.log
          stderr.log
          metrics.json
  summary.csv
  leaderboard.csv
  summary.md
```

说明：

- `views/` 是按需物化的数据视图缓存，默认使用软链接
- `workdirs/` 是底层训练框架的原生输出目录
- `records/` 是 benchmark harness 自己的标准化运行记录

## 8. Phase 1 MVP

### 8.1 `split_dataset.py`

职责：

- 扫描 `DOTA` 全集
- 生成固定 `test`
- 为多个 `split_seed` 生成 `train/val`
- 写出 `split_manifest.json`
- 写出 `split_summary.json`

`split_manifest.json` 至少包含：

- `dataset_name`
- `holdout_seed`
- `test_ratio`
- `val_ratio`
- `split_seeds`
- 每个 split 的：
  - `train_ids`
  - `val_ids`
  - `test_ids`

`split_summary.json` 至少包含：

- 每个 split 的样本数
- 正负样本比例
- `class_mask` 分布
- `instance_count_bucket` 分布

### 8.2 `run_suite.py`

职责：

- 读取 `split_manifest.json`
- 读取 benchmark 配置与模型矩阵
- 按 `model × split_seed × train_seed` 串行调度
- 按需物化 `DOTA` 或 `YOLO OBB` 视图
- 调用对应环境中的训练/测试子进程
- 生成每次 run 的 `metrics.json`
- 在 suite 结束后生成：
  - `summary.csv`
  - `leaderboard.csv`
  - `summary.md`

第一版必须支持：

- resume
- 跳过已成功 run
- 单个失败 run 重跑
- 只跑指定模型
- 只跑指定 `split_seed`
- 只跑指定 `train_seed`

第一版不做：

- 并发训练
- 分布式调度
- 跨节点恢复

### 8.3 Phase 1 的明确边界

第一版明确只做两件对外事情：

1. 切分
2. 跑完整套实验并收集结果

因此以下能力都收敛到 `run_suite.py` 内部：

- 数据视图按需物化
- 结果即时汇总

只有当后续出现明确需求时，才拆出：

- `materialize_splits.py`
- `collect_results.py`

拆分触发条件如下：

- 需要只重收集、不重跑
- 需要跨多个历史 benchmark 统一回收结果
- 需要长期保留可复用的数据视图目录

## 9. 环境策略

### 9.1 总体原则

第一版不追求单环境统一，明确拆成两套环境：

- `mmrotate`
- `yolo`

原因很直接：

- `MMRotate/MMCV` 对 Python、Torch、CUDA 组合更敏感
- `YOLO11-OBB` 依赖更宽松
- 强行单环境只会增加安装与维护风险

### 9.2 验证目标

第一版的首要验证目标固定为：

- AutoDL Ubuntu
- 单机单卡
- `4090`
- 基础镜像选择 `torch 2.8 + python 3.12 + cuda 12.8`

说明：

- 这里的基础镜像只是提供操作系统与 CUDA 底座
- 不直接复用镜像内置的 Python 依赖栈
- 依赖仍由 `uv` 在各自环境中单独安装

`5090` 不作为第一版首个验证目标。
如果 `4090` smoke 通过，再扩展到 `5090`。

### 9.3 `mmrotate` 环境

`mmrotate` 环境以仓库现有 `saki-plugin-oriented-rcnn/uv.lock` 为依据，固定为：

- `Python 3.12`
- `torch 2.9.1`
- `torchvision 0.24.1`
- `onedl-mmengine 0.10.9`
- `onedl-mmcv 2.3.2.post2`
- `onedl-mmdetection 3.4.5`
- `onedl-mmrotate 1.1.0.post1`

适用模型：

- `Oriented R-CNN`
- `RoI Transformer`
- `R3Det`
- `RTMDet-Rotated`

### 9.4 `yolo` 环境

`yolo` 环境以仓库现有 `saki-plugin-yolo-det/uv.lock` 为依据，固定为：

- `Python 3.12`
- `torch 2.10.0`
- `torchvision 0.25.0`
- `ultralytics 8.4.14`

适用模型：

- `YOLO11m-OBB`

### 9.5 orchestration 层的调用方式

第一版统一采用子进程调用：

- MMRotate 模型通过 `uv run --project benchmarks/obb_baseline/envs/mmrotate ...`
- YOLO 模型通过 `uv run --project benchmarks/obb_baseline/envs/yolo ...`

结论只有一个：

- orchestration 进程不直接 import 重框架
- 所有重框架都在各自环境的子进程中运行

## 10. 结果口径与汇总规则

### 10.1 主指标

第二部分主排序指标固定为：

- `mAP50_95`

### 10.2 辅助指标

用于解释差异，但不参与主排序：

- `mAP50`
- `precision`
- `recall`
- `f1`

### 10.3 工程补充指标

仅用于附带讨论，不参与“最佳基线模型”的判定：

- `train_time_sec`
- `infer_time_ms`
- `peak_mem_mb`
- `param_count`
- `checkpoint_size_mb`

第一版要求如下：

- 可以记录
- 可以展示
- 但不得参与 leaderboard 排序
- 若某框架无法稳定提供，允许写 `null`

### 10.4 每次 run 的标准产物

每次 run 必须产出一份统一格式的 `metrics.json`。

`metrics.json` 至少包含：

- `benchmark_name`
- `split_manifest_hash`
- `model_name`
- `preset`
- `holdout_seed`
- `split_seed`
- `train_seed`
- `status`
- `mAP50_95`
- `mAP50`
- `precision`
- `recall`
- `f1`
- `train_time_sec`
- `infer_time_ms`
- `peak_mem_mb`
- `param_count`
- `checkpoint_size_mb`
- `artifact_paths`

说明：

- 核心精度字段不得缺失
- 工程补充字段允许为 `null`

### 10.5 汇总文件定义

第一版统一输出三份 suite 级文件：

- `summary.csv`
  - 一行一个 run
  - 默认按 `model_name`、`split_seed`、`train_seed` 升序排列
- `leaderboard.csv`
  - 一行一个模型
  - 按 `mAP50_95` 的总均值排序
- `summary.md`
  - 面向人工阅读的简要结论
  - 默认跟随 `leaderboard.csv` 的模型排序

### 10.6 聚合规则

聚合分两层：

1. 在同一 `split_seed` 内，对多个 `train_seed` 求 `mean ± std`
2. 再跨所有 `split_seed` 求总 `mean ± std`

第二部分正文中的模型排序，按总 `mAP50_95 mean` 排序。

结论措辞应写成：

- “精度最佳模型”

不写成：

- “综合最优模型”

## 11. 第二部分与第三部分的目录关系

第二部分与第三部分必须使用不同的 `benchmark_name`，不得混写在同一个结果目录下。

推荐方式：

- 第二部分：
  - `runs/obb_baseline/fedo_part2_v1/`
- 第三部分：
  - `runs/obb_baseline/fedo_part3_orcnn_v1/`

两者关系如下：

- 可以共享同一份 `split_manifest.json`
- 或者第三部分显式引用第二部分的 `split_manifest_path`
- 但两部分的 `leaderboard.csv` 和 `summary.md` 必须分开生成

这样做的原因是：

- 第二部分回答“代表性基线比较”
- 第三部分回答“在固定基线上的改进效果”
- 两者是同源实验，不是同一张榜单

## 12. 实施顺序

第一版交付边界只包含两个阶段：

- `Stage 0`：环境与链路 smoke
- `Stage 1`：第二部分全量实验

第三部分复用属于第一版完成后的直接后续使用方式，不计入第一版交付边界。

### 12.1 Stage 0：环境与链路 smoke

先只打通最小矩阵：

- 模型：
  - `YOLO11m-OBB`
  - `Oriented R-CNN`
- split：
  - `1 个 split_seed`
- 训练随机性：
  - `1 个 train_seed`

目标不是得出论文结论，而是验证：

- 两套环境能安装
- 两条训练链路能跑通
- `metrics.json` 结构统一
- `summary.csv` 和 `leaderboard.csv` 能生成

### 12.2 Stage 1：第二部分全量实验

在 smoke 通过后，执行完整矩阵：

- `5 个模型`
- `3 个 split_seed`
- `3 个 train_seed`

总计：

- `45 runs`

### 12.3 第一版完成后的直接复用

第三部分不再重新设计 benchmark harness，只做两件事：

- 复用已有 `split_manifest`
- 在独立 `benchmark_name` 下跑 `Oriented R-CNN` 改进实验

## 13. 风险与应对

### 13.1 环境兼容风险

风险：

- `MMRotate/MMCV` 安装失败

应对：

- 第一版只以 `4090 + CUDA 12.8` 为首个验证目标
- 严格按现有 `uv.lock` 固定版本
- 明确拆成 `mmrotate` 与 `yolo` 两套环境

### 13.2 数据对齐风险

风险：

- `DOTA` 与 `YOLO OBB` 导出之间 stem 不一致

应对：

- `run_suite.py` 在首次构建 `YOLO OBB` 视图时强制校验 stem
- 不一致直接失败，不做隐式修复

### 13.3 小 strata 切分风险

风险：

- 负样本过多，或某些类别组合太稀疏，导致严格分层失败

应对：

- 使用三级回退分层键
- 第一版优先保证 split 稳定可复现，而不是追求复杂最优分层

### 13.4 工程指标可比性风险

风险：

- 不同框架对时延、显存、参数量的统计口径天然不完全一致

应对：

- 这些指标只作补充说明
- 不进入主排序
- 若采集不稳定，允许在 `metrics.json` 中保留为 `null`

## 14. 结论

第一版最终采用的方案是：

- 独立 benchmark 目录
- 两个外部脚本
- 两套 `uv` 环境
- 一个统一的 `metrics.json` 契约
- 第二部分与第三部分共享 split、分开出榜

这个方案满足三个目标：

- 对论文叙事足够清晰
- 对工程实现足够克制
- 对后续第三部分改进实验足够可复用
