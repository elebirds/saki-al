# Aug IoU Bounded Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `aug_iou_disagreement` 的 score 路径重构为“四段有界流水线”，提升 GPU 利用率并缩短慢样本排查路径。

**Architecture:** 继续复用 executor 现有的样本下载与本地缓存；插件内部改为“多线程预处理 -> 单 GPU 批量推理 -> 多线程后处理/打分”的有界流水线。保留现有 score driver 与进度语义，但新增批次级与慢样本级诊断日志。

**Tech Stack:** Python 3.11, `concurrent.futures`, YOLO/Ultralytics, Pillow, NumPy, pytest

---

## Chunk 1: 流水线接口与配置

### Task 1: 明确配置入口与默认值

**Files:**
- Modify: `saki-plugins/saki-plugin-yolo-det/plugin.yml`
- Modify: `saki-plugins/saki-plugin-yolo-det/src/saki_plugin_yolo_det/config_service.py`
- Test: `saki-plugins/saki-plugin-yolo-det/tests/test_plugin_v2_context_and_config.py`

- [ ] **Step 1: 写失败测试**

在 `test_plugin_v2_context_and_config.py` 中增加：
- `aug_iou_sample_batch_size` 默认值与裁剪
- `aug_iou_pipeline_workers` 默认值与裁剪

- [ ] **Step 2: 运行失败测试确认红灯**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_plugin_v2_context_and_config.py -q`
Expected: FAIL，提示新字段缺失或默认值不符合预期

- [ ] **Step 3: 实现最小配置支持**

在 manifest 与 `YoloConfigService` 中增加新字段：
- `aug_iou_sample_batch_size`
- `aug_iou_pipeline_workers`

- [ ] **Step 4: 重跑配置测试确认通过**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_plugin_v2_context_and_config.py -q`
Expected: PASS

## Chunk 2: 纯流水线编排

### Task 2: 为 `aug_iou` 增加可测试的有界流水线编排

**Files:**
- Modify: `saki-plugins/saki-plugin-yolo-det/src/saki_plugin_yolo_det/predict_pipeline.py`
- Test: `saki-plugins/saki-plugin-yolo-det/tests/test_predict_pipeline.py`

- [ ] **Step 1: 写失败测试**

在 `test_predict_pipeline.py` 中增加：
- 多样本增强工作项会合并为一次批量 infer
- 超过样本批大小时会分成多个 infer 批次
- 结果会按样本切回并保持逐样本进度回调
- 批次诊断回调可收到 `samples/views/infer_sec`

- [ ] **Step 2: 运行失败测试确认红灯**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_predict_pipeline.py -q`
Expected: FAIL，提示新流水线函数/行为不存在

- [ ] **Step 3: 实现最小流水线**

在 `predict_pipeline.py` 中增加：
- 预处理工作项数据结构
- 有界预处理/推理/后处理编排
- 保留原单样本路径作为兼容回退

- [ ] **Step 4: 重跑流水线测试确认通过**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_predict_pipeline.py -q`
Expected: PASS

## Chunk 3: YOLO 服务接线与诊断日志

### Task 3: 将 `aug_iou` score 接到新流水线

**Files:**
- Modify: `saki-plugins/saki-plugin-yolo-det/src/saki_plugin_yolo_det/predict_service.py`
- Test: `saki-plugins/saki-plugin-yolo-det/tests/test_predict_service_obb.py`

- [ ] **Step 1: 写失败测试**

在 `test_predict_service_obb.py` 中增加：
- `aug_iou` score 会把多个样本的增强视图合并后调用一次 `model.predict`
- 批次日志/慢样本日志会带上 `sample_batch_size` 与 `pipeline_workers`

- [ ] **Step 2: 运行失败测试确认红灯**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_predict_service_obb.py -q`
Expected: FAIL，提示仍走旧单样本路径

- [ ] **Step 3: 实现服务层接线**

在 `predict_service.py` 中：
- 读取新配置
- 复用现有模型缓存
- 为内存源推理增加降批回退
- 输出批次级、慢样本级、进度级日志

- [ ] **Step 4: 重跑服务测试确认通过**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_predict_service_obb.py -q`
Expected: PASS

## Chunk 4: 回归验证与提交

### Task 4: 运行关键回归并提交

**Files:**
- Verify only

- [ ] **Step 1: 运行插件关键测试**

Run: `uv run --project saki-plugins/saki-plugin-yolo-det pytest saki-plugins/saki-plugin-yolo-det/tests/test_predict_pipeline.py saki-plugins/saki-plugin-yolo-det/tests/test_predict_service_obb.py saki-plugins/saki-plugin-yolo-det/tests/test_plugin_v2_context_and_config.py -q`
Expected: PASS

- [ ] **Step 2: 运行 executor 相关回归**

Run: `uv run --project saki-executor pytest saki-executor/tests/test_sampling_service.py saki-executor/tests/test_pipeline_stage_service.py -q`
Expected: PASS

- [ ] **Step 3: 检查 diff 与提交**

Run: `git status --short`
Expected: 仅包含本次相关改动

- [ ] **Step 4: 提交**

```bash
git add docs/superpowers/plans/2026-03-28-aug-iou-bounded-pipeline.md \
  saki-plugins/saki-plugin-yolo-det/plugin.yml \
  saki-plugins/saki-plugin-yolo-det/src/saki_plugin_yolo_det/config_service.py \
  saki-plugins/saki-plugin-yolo-det/src/saki_plugin_yolo_det/predict_pipeline.py \
  saki-plugins/saki-plugin-yolo-det/src/saki_plugin_yolo_det/predict_service.py \
  saki-plugins/saki-plugin-yolo-det/tests/test_plugin_v2_context_and_config.py \
  saki-plugins/saki-plugin-yolo-det/tests/test_predict_pipeline.py \
  saki-plugins/saki-plugin-yolo-det/tests/test_predict_service_obb.py
git commit -m "refactor(yolo): pipeline aug iou score batching"
```
