# Prepared Data Cache Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `prepared_data_v2` 增加索引、24 小时 TTL 和 10GB 容量淘汰，阻止训练预处理缓存无限增长。

**Architecture:** 新增 `PreparedDataCache` helper 统一管理 `prepared_data_v2` 根目录下的索引、touch 与 prune；`Workspace` 继续负责恢复和写入目录，但将 prepared cache 的元数据维护与清理委托给 helper。启动时执行一次 best-effort prune，写入成功后执行一次 protected prune。

**Tech Stack:** Python, pathlib, json, pytest, saki-executor

---

## Chunk 1: 配置与测试基线

### Task 1: 先写 prepared data cache 行为测试

**Files:**
- Create: `saki-executor/tests/test_prepared_data_cache.py`
- Modify: `saki-executor/tests/test_workspace.py`

- [ ] **Step 1: 为 helper 写命中 touch 测试**

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `cd /Users/hhm/code/saki && pytest saki-executor/tests/test_prepared_data_cache.py -q`
Expected: FAIL，缺少 helper 或行为未实现

- [ ] **Step 3: 为 TTL、LRU、脏项清理写失败测试**

- [ ] **Step 4: 为 workspace 命中更新索引补失败测试**

- [ ] **Step 5: 再次运行相关测试并确认失败原因正确**

Run: `cd /Users/hhm/code/saki && pytest saki-executor/tests/test_prepared_data_cache.py saki-executor/tests/test_workspace.py -q`
Expected: FAIL，失败点集中在 prepared data cache 新行为

## Chunk 2: helper 实现与接线

### Task 2: 实现 prepared data cache helper

**Files:**
- Create: `saki-executor/src/saki_executor/cache/prepared_data_cache.py`
- Modify: `saki-executor/src/saki_executor/core/config.py`

- [ ] **Step 1: 增加配置项**

- [ ] **Step 2: 实现索引加载、保存和目录大小统计**

- [ ] **Step 3: 实现 `touch()` 与 `register()`**

- [ ] **Step 4: 实现 `prune()`，按脏项 -> TTL -> LRU 顺序执行**

- [ ] **Step 5: 运行 helper 测试并确认通过**

Run: `cd /Users/hhm/code/saki && pytest saki-executor/tests/test_prepared_data_cache.py -q`
Expected: PASS

### Task 3: 将 workspace 和启动流程接到 helper

**Files:**
- Modify: `saki-executor/src/saki_executor/steps/workspace.py`
- Modify: `saki-executor/src/saki_executor/main.py`

- [ ] **Step 1: 在 workspace restore 路径接入 touch**

- [ ] **Step 2: 在 workspace store 路径接入 register + protected prune**

- [ ] **Step 3: 在 executor 启动流程接入 startup prune**

- [ ] **Step 4: 运行 workspace 相关测试并确认通过**

Run: `cd /Users/hhm/code/saki && pytest saki-executor/tests/test_workspace.py saki-executor/tests/test_pipeline_stage_service.py -q`
Expected: PASS

## Chunk 3: 回归验证

### Task 4: 运行回归并核对无额外破坏

**Files:**
- Modify: none

- [ ] **Step 1: 运行本次涉及的测试集合**

Run: `cd /Users/hhm/code/saki && pytest saki-executor/tests/test_prepared_data_cache.py saki-executor/tests/test_workspace.py saki-executor/tests/test_pipeline_stage_service.py -q`
Expected: PASS

- [ ] **Step 2: 检查失败是否仅与本次改动相关**

- [ ] **Step 3: 整理实现说明与残余风险**
