# Runtime Loop 策略 V4（当前生效）

> 生效日期：2026-02-28  
> 适用范围：`saki-api` / `saki-dispatcher` / `saki-web`

## 1. 三层语义（唯一真值）

1. `lifecycle`：Loop 生命周期真值（持久化）。  
2. `phase`：执行指针（持久化）。  
3. `gate`：交互决策（实时计算，不持久化）。  

## 2. 命名与字段硬切

1. `LoopStatus` -> `LoopLifecycle`  
2. `LoopStage` -> `LoopGate`  
3. API 字段：`state -> lifecycle`，`stage -> gate`，`stage_meta -> gate_meta`  
4. 路由：`GET /api/v1/loops/{loop_id}/gate`（`/stage` 已移除）  

## 3. Gate 集合（新值）

1. `need_snapshot`
2. `need_labels`
3. `can_start`
4. `running`
5. `paused`
6. `stopping`
7. `need_round_labels`
8. `can_confirm`
9. `can_next_round`
10. `can_retry`
11. `completed`
12. `stopped`
13. `failed`

## 4. 判定优先级

`gate` 计算顺序固定为：

1. 终态 lifecycle：`failed/completed/stopped`
2. 运行态 lifecycle：`running/paused/stopping`
3. 启动态 lifecycle：`draft`（仅此分支检查 `need_snapshot/need_labels`）

## 5. 动作规则

1. `POST /api/v1/loops/{loop_id}:act` 是 loop 生命周期动作唯一入口。  
2. `confirm` 为 reveal-only，不创建下一轮。  
3. `start_next_round` 负责创建下一轮。  
4. `start` 仅允许 `draft -> running`。  
5. `start_next_round` 仅允许：`lifecycle=running + phase=al_wait_user + latest_round.confirmed_at!=null + no in-flight step`。  
6. `paused` 下必须先 `resume`，不能直接 `start_next_round`。  
7. `stopped` 为终态，不可重启。  

## 6. Snapshot 与可见性

`GET /loops/{loop_id}/snapshot` 返回三组计数：

1. `frozen_partition_counts`（静态 manifest）
2. `virtual_visibility_counts`（动态可见性）
3. `effective_split_counts`（训练/验证/测试有效视图）

## 7. Confirm 阈值

1. `selected_count=0` 时：`effective_min_required=0`。  
2. 否则：`effective_min_required=min(configured_min_required, selected_count)`。  
3. reveal/confirm 按 `round_id` 读取候选，禁止按 `round_index` 混读 attempt。  

## 8. 旧术语映射

1. `status` -> `lifecycle`
2. `stage` -> `gate`
3. `running_round` -> `running`
4. `ready_to_start` -> `can_start`
5. `label_gap_required` -> `need_labels`
6. `snapshot_required` -> `need_snapshot`
7. `waiting_round_label` -> `need_round_labels`
8. `ready_to_confirm` -> `can_confirm`
9. `ready_next_round` -> `can_next_round`
10. `failed_retryable` -> `can_retry`

## 9. 废弃清单（已删除）

1. `/loops/{loop_id}/stage`
2. Loop 读模型中的 `state/stage/stage_meta`
3. loop 生命周期层面的 `status` 字段/类型命名
