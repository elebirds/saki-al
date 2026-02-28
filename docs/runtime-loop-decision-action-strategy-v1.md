# Runtime Loop 策略 V2（当前生效）

> 生效日期：2026-02-28  
> 适用范围：`saki-api` / `saki-dispatcher` / `saki-executor` / `saki-web`

## 1. 核心原则

1. `Round` 只表达**执行态**：`pending/running/completed/failed/cancelled`。  
2. `Stage` 只表达**交互态**：是否需要用户补标、确认、重试等。  
3. Loop 生命周期动作唯一入口：`POST /api/v1/loops/{loop_id}:act`。  
4. TopK 明细调整走 round 专用接口，不混入 `:act`：
   - `GET /api/v1/rounds/{round_id}/selection`
   - `POST /api/v1/rounds/{round_id}/selection:apply`
   - `POST /api/v1/rounds/{round_id}/selection:reset`
5. 全链路硬切：不保留兼容入口、字段别名与 legacy payload 回退。

### 1.1 硬切约束（无兼容回退）

1. `RetryRoundRequest` 不再接受 `use_latest_inputs`，重跑固定使用当前最新分支头与 loop 配置。  
2. 前端不再接受 `status -> state` 回退，loop/summary/action 响应必须提供 `state`。  
3. dispatcher 配置解析不再回退 legacy 结构（`simulation` 顶层段、顶层 `round_resources_default`）。  
4. 标注缺口判定只基于 `commit_sample_state`，不再回退 `CAMap`。  

---

## 2. Round/Stage 语义切分

### 2.1 Round

1. AL round 执行完成后状态为 `completed`，不再写 `wait_user`。  
2. 是否“待用户确认”通过 `loop.phase=al_wait_user + stage` 表达。  
3. API 返回 `RoundRead.awaiting_confirm` 仅用于 UI 提示，不参与执行状态机。

### 2.2 Stage

当前阶段：

1. `snapshot_required`
2. `label_gap_required`
3. `ready_to_start`
4. `running_round`
5. `waiting_round_label`
6. `ready_to_confirm`
7. `failed_retryable`
8. `completed`
9. `stopped`
10. `failed`

---

## 3. 统一阈值规则

`effective_min_required` 统一定义：

1. `selected_count == 0` 时固定为 `0`（允许空选样轮确认推进）  
2. 其他情况为 `min(configured_min_required, selected_count)`

该规则在 API 判定与 dispatcher confirm 路径保持一致。

---

## 4. Attempt 隔离（关键修复）

`ResolveRoundReveal` 全面改为按 `round_id` 计算，不再按 `round_index` 聚合。  
效果：

1. 重试后只读取“最新 attempt 的 select 候选”  
2. 旧 attempt 候选不再污染 reveal/confirm 判定

---

## 5. TopK 人工覆写（可选）

默认仍自动 TopK，用户可选 include/exclude 覆写。

### 5.1 覆写约束

1. 仅 `active_learning` 且最新 round/latest attempt 可调整  
2. 仅 loop 处于 `al_wait_user` 阶段可写  
3. `include` 必须来自 `score_pool`，否则拒绝

### 5.2 生效算法

输入：`auto_selected`、`score_pool`、`include_ids`、`exclude_ids`、`topk`

1. 从 `auto_selected` 移除 `exclude`
2. 追加 `include`（保序去重）
3. 超过 `topk` 截断
4. 不足 `topk` 时从 `score_pool` 高分回填

输出覆盖 `select` 步骤候选；覆写记录写入 `al_round_selection_override`。

---

## 6. Review Pool 扩容策略

为支持 include/backfill，`score` 步骤产出候选池采用：

1. `sampling.review_pool_multiplier`（默认 `3`，最小 `1`）
2. `review_pool_size = topk * review_pool_multiplier`

执行侧规则：

1. `score` 步骤按 `review_pool_size` 产出候选
2. `select` / confirm 仍按 `topk` 生效

---

## 7. 各服务职责

### 7.1 saki-api

1. Decision Engine 纯读实时判定 `stage/actions/decision_token`
2. `:act` 执行动作并返回最新决策快照
3. selection 专用 API 管理 include/exclude 与 select 候选重算

### 7.2 saki-dispatcher

1. `confirm` 与 preflight reveal 改为 round_id 路径
2. AL round `completed` 后推进 loop 到 `al_wait_user`
3. 不再把 round 状态改写为 `WAIT_USER`

### 7.3 saki-executor

step 语义按类型分流：

1. `train`：仅训练 + 产物上传
2. `score`：仅打分/采样（支持 review_pool_size）
3. `eval`：仅评估
4. `export`：仅导出
5. `upload_artifact`：仅上传制品
6. `custom`：保留训练+采样扩展路径

---

## 8. 数据与迁移约束

1. 业务上禁止再写入 `round.state=WAIT_USER`
2. 历史 `WAIT_USER` 在迁移中一次性修正为 `COMPLETED`
3. 新增 `al_round_selection_override` 表存储人工覆写审计

---

## 9. 前端对齐要求

1. Continue 主按钮只执行后端 `primary_action`
2. 高级动作从后端 `actions` 渲染，不硬编码分支
3. round 状态展示不再出现 `wait_user`，改为 `completed + awaiting_confirm` 标签
4. `selection_adjust` 打开 TopK 调整弹窗，调用 round selection 专用 API
