# Snapshot Grouped Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Saki 的 loop snapshot 在初始化与 append_split 时按原图组切分，避免 DOTA patch 从同一原图泄露到 train/val/test 不同分区。

**Architecture:** 在 `snapshot_lifecycle_mixin` 中通过 runtime 自身的 `snapshot_query_repo` 批量读取 `name` 与 `meta_info.original_relative_path`，在 `snapshot_policy_mixin` 中解析 group key 并先按组分配、再展开为 sample 级 rows。无法识别组的普通样本继续维持现有逐 sample 随机切分行为。

**Tech Stack:** Python, SQLModel, pytest, saki-api runtime service

---

## Chunk 1: 纯逻辑分区改造

### Task 1: 为 snapshot policy 增加 group-aware 分配测试

**Files:**
- Modify: `saki-api/tests/runtime/test_snapshot_split_logic.py`

- [x] **Step 1: 写失败测试，覆盖 init/append_split 的同组不跨分区行为**

- [x] **Step 2: 运行目标测试并确认在现状下失败**

Run: `cd /Users/hhm/code/saki/.worktrees/main/saki-api && uv run pytest tests/runtime/test_snapshot_split_logic.py -q`

- [x] **Step 3: 为普通样本保留回退行为增加测试**

- [x] **Step 4: 再次运行目标测试，确认失败原因正确**

### Task 2: 在 snapshot policy 中实现 group-aware 组分配

**Files:**
- Modify: `saki-api/src/saki_api/modules/runtime/service/runtime_service/snapshot_policy_mixin.py`

- [x] **Step 1: 增加 group key 解析辅助函数**

- [x] **Step 2: 增加按组洗牌与配额分配逻辑**

- [x] **Step 3: 让 init/append_split 使用 sample 记录输入并展开成 sample rows**

- [x] **Step 4: 运行 `test_snapshot_split_logic.py`，确认全部通过**

Run: `cd /Users/hhm/code/saki/.worktrees/main/saki-api && uv run pytest tests/runtime/test_snapshot_split_logic.py -q`

## Chunk 2: Lifecycle 接线与集成验证

### Task 3: 扩展 runtime sample 查询入口，向 snapshot lifecycle 提供 sample metadata

**Files:**
- Modify: `saki-api/src/saki_api/modules/runtime/repo/snapshot_query.py`
- Modify: `saki-api/src/saki_api/modules/runtime/service/runtime_service/snapshot_lifecycle_mixin.py`

- [x] **Step 1: 为 runtime snapshot 查询仓库增加批量读取 Sample 记录的方法**

- [x] **Step 2: 在 lifecycle 中把 init/update 的候选样本改为 sample records 驱动**

- [x] **Step 3: 确认 append_all_to_pool 路径不受影响**

### Task 4: 增加 service 级测试验证 snapshot init/update 不跨原图组

**Files:**
- Modify: `saki-api/tests/runtime/test_loop_api_contract.py`

- [x] **Step 1: 扩展测试种子样本 helper，允许指定 `name/meta_info`**

- [x] **Step 2: 新增 init snapshot 分组切分测试**

- [x] **Step 3: 新增 update append_split 分组切分测试**

- [x] **Step 4: 运行目标集成测试并确认通过**

Run: `cd /Users/hhm/code/saki/.worktrees/main/saki-api && uv run pytest tests/runtime/test_loop_api_contract.py -k 'snapshot and group' -q`

## Chunk 3: 回归验证

### Task 5: 执行相关测试回归并检查无额外破坏

**Files:**
- Modify: none

- [x] **Step 1: 运行 snapshot 相关测试集合**

Run: `cd /Users/hhm/code/saki/.worktrees/main/saki-api && uv run pytest tests/runtime/test_snapshot_split_logic.py tests/runtime/test_loop_api_contract.py -k snapshot -q`

- [x] **Step 2: 检查失败项是否仅与本次改动相关**

- [x] **Step 3: 整理实现说明与残余风险**
