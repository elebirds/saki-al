# Runtime Loop 策略 V3（当前生效）

> 生效日期：2026-02-28  
> 适用范围：`saki-api` / `saki-dispatcher` / `saki-executor` / `saki-web`

## 1. 核心原则

1. `Round` 只表达执行态：`pending/running/completed/failed/cancelled`。  
2. `Stage` 只表达交互态：补标、确认、下一轮启动、重试等。  
3. Loop 生命周期动作统一入口：`POST /api/v1/loops/{loop_id}:act`。  
4. TopK 明细编辑固定在 round-step 层，不放 project 层真值。  
5. 全链路硬切，不保留旧字段兼容回退。

## 2. Confirm 两步化

### 2.1 语义

1. `confirm`：只做 reveal + 写入 round 确认元数据，不创建下一轮。  
2. `start_next_round`：仅在 `ready_next_round` 阶段可执行，负责真正创建下一轮。  

### 2.2 阶段

1. `snapshot_required`
2. `label_gap_required`
3. `ready_to_start`
4. `running_round`
5. `waiting_round_label`
6. `ready_to_confirm`
7. `ready_next_round`
8. `failed_retryable`
9. `completed`
10. `stopped`
11. `failed`

## 3. Snapshot 统计语义

`GET /loops/{loop_id}/snapshot` 返回三组计数：

1. `frozen_partition_counts`：manifest 冻结分区计数（静态）。  
2. `virtual_visibility_counts`：训练可见性计数（动态）。
   - `train_visible_total`
   - `train_visible_seed`
   - `train_visible_revealed_from_pool`
   - `train_pool_hidden`
3. `effective_split_counts`：当前有效 train/val/test 视图计数。
   - `train_effective`
   - `val_effective`
   - `test_effective`

## 4. Round 确认元数据

`RoundRead` 新增：

1. `confirmed_at`
2. `confirmed_commit_id`
3. `confirmed_revealed_count`
4. `confirmed_selected_count`
5. `confirmed_effective_min_required`

说明：
1. `awaiting_confirm=true` 仅在 `confirmed_at is null` 时成立。  
2. 进入 `ready_next_round` 后该轮 selection 覆写锁定为只读。

## 5. 阈值与 attempt 隔离

1. `effective_min_required = 0` 当 `selected_count=0`。  
2. 否则 `effective_min_required = min(configured_min_required, selected_count)`。  
3. reveal/confirm 一律按 `round_id` 读取 select 候选，不按 `round_index` 聚合。

## 6. 各端职责

### 6.1 saki-api

1. 实时判定 `stage/actions/decision_token`。  
2. `:act` 执行 `confirm/start_next_round/...`。  
3. 提供 snapshot 三组计数。  

### 6.2 saki-dispatcher

1. `ConfirmLoop` 改为 reveal-only。  
2. 新增 `StartNextRound` 命令。  
3. 仅在显式 `start_next_round` 时创建下一轮。  

### 6.3 saki-web

1. Continue 主按钮严格跟随 `primary_action`。  
2. `ready_to_confirm` 显示 `Confirm Reveal`。  
3. `ready_next_round` 显示 `Start Next Round`。  
4. Snapshot 面板分开展示冻结分区、虚拟可见性、有效 split。

## 7. 数据迁移约束

1. 新增 round 确认字段并保留历史空值。  
2. 不新增 project 级 selection 真值表。  
3. selection 真值仍是 `step_candidate_item(step_id)` + `al_round_selection_override(round_id)`。
