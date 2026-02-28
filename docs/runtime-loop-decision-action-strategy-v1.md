# Runtime Loop 判定与动作统一策略（当前生效版）

> 生效日期：2026-02-28  
> 适用范围：`saki-api` / `saki-dispatcher` / `saki-web`（Loop 控制面）

## 1. 目标与边界

本策略统一两件事：

1. **判定（Decision）**：实时计算 `stage + actions + guards`，只读、无副作用。  
2. **转移（Action）**：统一由单入口动作执行，所有写操作从同一路径进入。

`phase` 继续作为 dispatcher 执行指针；`stage` 作为用户可见决策视图。两者职责分离，不互相替代。

---

## 2. 当前单一入口

### 2.1 唯一动作入口

`POST /api/v1/loops/{loop_id}:act`

请求体：

1. `action`：动作枚举（可选；不传则执行当前 `primary_action`）
2. `force`：强制执行标记（可选）
3. `decision_token`：防并发陈旧 token（可选但推荐）
4. `payload`：动作参数

响应体：

1. `executed_action`
2. `command_id`（dispatcher 命令类动作）
3. `stage/stage_meta/primary_action/actions`
4. `decision_token/blocking_reasons`
5. `phase/state`

### 2.2 Stage 查询入口（纯读）

`GET /api/v1/loops/{loop_id}/stage`

要求：

1. 不写库
2. 实时返回最新决策
3. 返回 `decision_token` 与 `blocking_reasons`

---

## 3. 旧入口处理策略

旧动作入口已全部从 API 路由删除，不再保留兼容路由：

1. `/loops/{id}:start`
2. `/loops/{id}:pause`
3. `/loops/{id}:resume`
4. `/loops/{id}:stop`
5. `/loops/{id}:confirm`
6. `/loops/{id}:continue`
7. `/loops/{id}/snapshot:init`
8. `/loops/{id}/snapshot:update`
9. `/rounds/{id}:retry`

---

## 4. 决策引擎规则（实时）

核心输出：`stage, stage_meta, primary_action, actions, decision_token, blocking_reasons`。

### 4.1 阈值统一规则

`effective_min_required`：

1. `selected_count <= 0` 时，固定为 `0`
2. 其余场景：`min(configured_min_required, selected_count)`

结果：

1. 支持空选样轮（`selected_count=0`）直接 `READY_TO_CONFIRM`
2. 避免被固定阈值卡死在 `WAITING_ROUND_LABEL`

### 4.2 Action 守卫

动作执行前必须重新决策并校验：

1. 若传入 `decision_token`，必须与当前 token 一致，否则 `409 DECISION_STALE`
2. 动作必须出现在当前 `actions`
3. 动作必须 `runnable=true`

---

## 5. Stage 与动作语义

当前主阶段：

1. `SNAPSHOT_REQUIRED`
2. `LABEL_GAP_REQUIRED`
3. `READY_TO_START`
4. `RUNNING_ROUND`
5. `WAITING_ROUND_LABEL`
6. `READY_TO_CONFIRM`
7. `FAILED_RETRYABLE`
8. `COMPLETED`
9. `STOPPED`
10. `FAILED`

关键约束：

1. `snapshot_required` 阶段不允许附加 `start`
2. `FAILED_RETRYABLE` 仅在“最新失败轮且无 in-flight step”出现
3. `retry_round` 仅重跑最新失败 attempt

---

## 6. 前端控制策略

`saki-web` 统一采用：

1. Continue 主按钮 = 执行 `primary_action`
2. 高级菜单 = 后端 `actions` 动态渲染
3. 不在前端硬编码 start/confirm/continue 分支逻辑
4. 所有动作均调用 `actLoop()`

---

## 7. 跨服务一致性

### 7.1 API（Python）

1. 决策：`SnapshotMixin.get_loop_stage()` 实时计算
2. 执行：`loop_control.act_loop()` 统一路由动作到 runtime 或 dispatcher

### 7.2 Dispatcher（Go）

`confirm` 路径的阈值不再本地重复推导，而是直接使用 RuntimeDomain 返回的 `effective_min_required`，确保：

1. `selected_count=0` 不阻塞推进
2. reveal 阈值判断与 API 侧一致
3. 规则单一来源，避免双端漂移

`confirm` 执行流程采用“两阶段”：

1. 预探测（无 loop 行锁）：先调用 RuntimeDomain 计算 reveal 结果  
2. 持锁复核（事务内）：锁定 loop 后校验 round/branch/min_required 是否仍匹配；匹配则复用预探测结果，不匹配再事务内重算  

该策略的目标是缩短持锁时间，降低 `DeadlineExceeded` 概率，同时保持并发正确性。

`start/retry` 的分支头解析采用 **DB 优先**（domain 仅兜底），避免命令链路被跨服务 RPC 卡住导致 `DeadlineExceeded`。

### 7.3 Executor（Python）

执行语义按 step_type 严格分流，不再“都走训练”：

1. `train/custom`：训练后可选采样
2. `score`：仅打分采样
3. `eval`：仅评估
4. `export`：仅导出
5. `upload_artifact`：仅上传制品

采样参数约束统一为：`active_learning/simulation` 仅 `score/custom` 强制要求 `sampling.strategy/topk`；`train/eval/export/upload_artifact` 不强制。

---

## 8. 过渡项

无。  
当前策略不保留旧入口兼容层，也不保留 `stage/stage_meta` 的写库缓存路径。

---

## 9. 本次对齐审计结论

审计结论：**主链路已对齐当前策略**。

已核对项：

1. Web 侧已无旧动作 API 调用，统一 `actLoop`
2. API 侧动作统一入口为 `:act`
3. 旧动作接口已从路由层删除
4. `stage` 查询无写库副作用
5. `selected_count=0` 在 API 与 dispatcher 双侧均可 confirm 推进

附注：

1. 历史规划文档仍可能出现旧接口示例；以本文件为准
