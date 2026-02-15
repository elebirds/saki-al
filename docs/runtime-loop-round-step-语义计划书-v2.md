# Saki Runtime 语义计划书 v2（Loop / Round / Step）

## 0. 文档目的

本文件定义 **saki-api / saki-dispatcher / saki-executor** 的统一运行时语义，作为后续代码重构、数据库命名重构、Proto 契约调整和前端交互实现的唯一依据。

本版重点吸收以下决策：

1. 顶层容器从 `ALLoop` 升级为 `Loop`（实验生命周期容器）。
2. 第二层从 `Job` 升级为 `Round`（单次迭代上下文）。
3. 第三层统一为 `Step`（最小逻辑单元）。
4. `SIMULATION` 中将 `AUTO_LABEL` 正式语义化为 `ACTIVATE_SAMPLES`，归属 `ORCHESTRATOR`。
5. 引入 `STOPPING` 并定义可恢复行为（重启后继续收敛到 `STOPPED`）。
6. 增加 `Cleanup` 语义：TTL + 用户按需清理。

---

## 1. 统一术语与命名重构

### 1.1 术语定义

1. `Loop`：实验生命周期容器，绑定一个 `branch`。
2. `Round`：Loop 中一次迭代执行上下文。
3. `Step`：Round 内最小执行单元。
4. `StepDispatchKind`：Step 的执行归属。
- `DISPATCHABLE`：需要下发 executor。
- `ORCHESTRATOR`：由 dispatcher 内部执行（事务动作/编排动作）。

### 1.2 旧名到新名映射

1. `ALLoop` -> `Loop`
2. `Job` -> `Round`
3. `JobTask` -> `Step`
4. `JobStatusV2` -> `RoundStatus`
5. `JobTaskStatus` -> `StepStatus`
6. `JobTaskType` -> `StepType`

### 1.3 重命名范围（必须统一）

1. Python 域模型类名、DTO 名、repo 名、service 名。
2. 数据库表名与约束名。
3. Proto message、RPC request/response 字段名。
4. 前端 API 字段名与页面文案。
5. 日志字段键名（`job_id` -> `round_id`，`task_id` -> `step_id`）。

---

## 2. 责任边界

1. `saki-api`
- 认证鉴权。
- 项目/分支/提交/标注域写入（L1/L2）。
- 北向 HTTP API。

2. `saki-dispatcher`
- 运行时编排（Loop/Round/Step 状态机）。
- executor 注册、心跳、分发、回收。
- runtime 域写入（L3）。
- ORCHESTRATOR Step 执行。

3. `saki-executor`
- 仅执行 `DISPATCHABLE` Step。
- 实时事件、指标、制品、结果回传。

---

## 3. 资源模型与主键关系

1. `loop`
- `id`, `project_id`, `branch_id`, `mode`, `state`, `phase`, `max_rounds`, `last_confirmed_commit_id`, `terminal_reason`。

2. `round`
- `id`, `loop_id`, `round_index`, `state`, `input_commit_id`, `output_commit_id`, `summary_metrics`, `terminal_reason`。

3. `step`
- `id`, `round_id`, `step_index`, `step_type`, `dispatch_kind`, `state`, `depends_on_step_ids`, `resolved_params`, `assigned_executor_id`, `attempt`。

4. 关键唯一约束
- `round(loop_id, round_index)` 唯一。
- `step(round_id, step_index)` 唯一。
- `step_event(step_id, seq)` 唯一。

5. 进度真值来源
- `Loop` 的轮次进度不以 `loop.current_round` 为真值。
- 真值来自 `SELECT MAX(round.round_index)`。

---

## 4. 状态机定义

### 4.1 LoopState

1. `DRAFT`
2. `RUNNING`
3. `PAUSED`
4. `STOPPING`
5. `STOPPED`
6. `COMPLETED`
7. `FAILED`

### 4.2 LoopPhase

1. AL 相关
- `AL_BOOTSTRAP`, `AL_TRAIN`, `AL_SCORE`, `AL_SELECT`, `AL_WAIT_USER`, `AL_EVAL`, `AL_FINALIZE`

2. Simulation 相关
- `SIM_BOOTSTRAP`, `SIM_TRAIN`, `SIM_SCORE`, `SIM_SELECT`, `SIM_ACTIVATE`, `SIM_EVAL`, `SIM_FINALIZE`

3. Manual 相关
- `MANUAL_BOOTSTRAP`, `MANUAL_TRAIN`, `MANUAL_EVAL`, `MANUAL_EXPORT`, `MANUAL_FINALIZE`

### 4.3 RoundState

1. `PENDING`
2. `RUNNING`
3. `WAIT_USER`
4. `COMPLETED`
5. `CANCELLED`
6. `FAILED`

### 4.4 StepState

1. `PENDING`
2. `READY`
3. `RUNNING`
4. `SUCCEEDED`
5. `FAILED`
6. `CANCELLED`
7. `SKIPPED`

### 4.5 终结原因（非状态）

1. `SUCCESS`
2. `USER_STOP`
3. `SYSTEM_ERROR`
4. `DATA_CONSTRAINT`

---

## 5. 模式策略（ModePolicy）

统一接口：

1. `build_round_plan(loop, round_index) -> StepSpec[]`
2. `on_round_completed(loop, round_result) -> NextAction`
3. `can_confirm(loop, context) -> GuardResult`
4. `should_stop(loop, history) -> bool`

### 5.1 ACTIVE_LEARNING

Round Plan：

1. `TRAIN (DISPATCHABLE)`
2. `SCORE (DISPATCHABLE)`
3. `EVAL (DISPATCHABLE)`
4. `SELECT_TOPK (ORCHESTRATOR)`
5. 进入 `AL_WAIT_USER`

推进策略：

1. 每轮结束进入 `WAIT_USER`。
2. 用户 `confirm` 后创建下一轮。
3. `confirm` 守卫：`new_labels_since(last_confirmed_commit_id) > 0` 或 `force=true`。

### 5.2 SIMULATION

Round Plan：

1. `TRAIN (DISPATCHABLE)`
2. `SCORE (DISPATCHABLE)`
3. `EVAL (DISPATCHABLE)`
4. `SELECT_TOPK (ORCHESTRATOR)`
5. `ACTIVATE_SAMPLES (ORCHESTRATOR)`
6. `ADVANCE_BRANCH (ORCHESTRATOR)`

推进策略：

1. 自动推进，不需要 `confirm`。
2. 可配置短冷却：`SIMULATION_ROUND_COOLDOWN_SEC`（默认 `5` 秒）。
3. 冷却仅影响“下一轮创建时机”，不改变结果语义。

### 5.3 MANUAL（普通深度学习训练）

Round Plan：

1. `TRAIN (DISPATCHABLE)`
2. `EVAL (DISPATCHABLE)`
3. `EXPORT (DISPATCHABLE)`

推进策略：

1. 单轮语义（默认 `max_rounds=1`）。
2. 无 `confirm`。
3. 轮成功后直接 `MANUAL_FINALIZE -> COMPLETED`。

---

## 6. 严格转移表（Loop）

| 当前状态 | 触发动作 | 守卫条件 | 下一状态 | 副作用 |
|---|---|---|---|---|
| DRAFT | start | - | RUNNING | 创建首轮（若不存在） |
| PAUSED | resume | - | RUNNING | 恢复 Tick |
| STOPPED | start | 允许重启策略开启 | RUNNING | 生成新 Round 或恢复未终态 Round |
| RUNNING | pause | - | PAUSED | 停止调度新 Step |
| RUNNING/PAUSED | stop | - | STOPPING | 广播取消在途 Step |
| STOPPING | 全部在途 Step 终态 | - | STOPPED | `terminal_reason=USER_STOP` |
| RUNNING | 系统不可恢复异常 | - | FAILED | `terminal_reason=SYSTEM_ERROR` |
| RUNNING | 模式策略判定完成 | - | COMPLETED | 进入 FINALIZE phase |

补充：`COMPLETED/FAILED` 默认不可 `resume`。

---

## 7. STOPPING 的可恢复语义（重启安全）

### 7.1 风险

dispatcher 在 `STOPPING` 过程中重启，导致取消信号未完全送达。

### 7.2 规范

1. Tick 线程必须扫描 `LoopState=STOPPING`。
2. 每次 Tick 对未终态 `Step(RUNNING/DISPATCHING/READY)` 重新执行 `CancelAttempt`。
3. `CancelAttempt` 必须幂等（以 `step_id + attempt` 去重）。
4. 当所有 Step 进入终态后，原子切换 `Loop STOPPING -> STOPPED`。
5. 若扫描超时（可配置）且存在僵尸 Step，标记 Round `CANCELLED` 并写审计告警。

---

## 8. ACTIVATE_SAMPLES 事务边界（跨 L2/L3）

### 8.1 语义目标

`SELECT_TOPK` 成功后，将样本从“未使用集合”激活到“训练可见集合”，并生成新的 branch 视图 commit。

### 8.2 原子性要求

1. 不允许“只更新了 L3 Step 成功，但 L2 Commit 未推进”。
2. 不允许“Commit 推进了，但 Step 失败导致无法追溯”。

### 8.3 建议实现（语义层）

1. `ACTIVATE_SAMPLES` 采用 **命令式幂等键**：`activation_key = loop_id + round_index + hash(sample_ids)`。
2. 调度器调用 `runtime_domain.ActivateSamples`（新 RPC，替代语义不清晰的 AutoLabel）。
3. `runtime_domain` 负责：
- 样本激活（L2）
- 生成 commit
- 推进 branch head
- 返回 `output_commit_id`
4. dispatcher 在同一编排事务内写入 Step 结果与 `output_commit_id`。
5. 若调用超时，按同 `activation_key` 重试，必须返回同一结果（幂等）。

---

## 9. SIMULATION 冷却与可观察性

### 9.1 冷却参数

1. `SIMULATION_ROUND_COOLDOWN_SEC`，默认 `5`。
2. `0` 表示关闭冷却（全速仿真）。

### 9.2 目的

1. 避免 Loop 轮转过快导致前端无法观察指标变化。
2. 提升本机（M4）演示可读性。

### 9.3 前端配套

1. 前端支持“自动播放步进”模式。
2. 每轮完成后给出固定停留窗口（如 2-3 秒）用于展示关键指标快照。

---

## 10. 日志与观测视图规范

### 10.1 事件挂载

1. 所有 runtime event 挂在 `step_id` 下。
2. Round/Loop 通过聚合视图读取（不重复写冗余日志）。

### 10.2 前端漏斗视图（必须）

1. 第一层：Loop 列表（状态、当前 phase、轮数进度）。
2. 第二层：Round 列表（每轮 summary、输入输出 commit）。
3. 第三层：Step 时间线（日志流、指标流、制品、错误）。

---

## 11. 产物与评估语义

### 11.1 制品下载

1. Step 产物统一记录 `artifact(kind,name,uri,meta)`。
2. 下载通过签名 URL 票据。

### 11.2 预测标注查看

1. `SCORE` 产出 `prediction_set`（绑定 loop/round/step）。
2. `prediction_item` 包含 `sample_id/category/geometry/confidence`。
3. 前端支持“按轮次回看预测标注”。

### 11.3 参数查看

1. `resolved_params` 固化在 Step 启动时。
2. 前端显示“生效参数”而非“当前全局参数”。

### 11.4 混淆矩阵

1. `EVAL` 产出结构化矩阵（JSON）+ 可下载文件（CSV/PNG）。
2. 与 Round 强绑定，支持历史对比。

---

## 12. Cleanup 语义（TTL + 按需）

### 12.1 保留策略

长期保留：

1. 训练权重、最终评估、混淆矩阵。
2. 每轮 TopK 结果与激活轨迹。

可清理：

1. 高频中间预测明细 `prediction_item`。
2. 临时中间文件。

### 12.2 TTL 清理

1. 配置：`PREDICTION_TTL_DAYS`。
2. 保留最近 N 轮 + pinned 轮次。

### 12.3 按需清理（用户触发）

新增语义动作：`cleanup_round_predictions(loop_id, round_index)`

1. 仅删除该轮中间预测明细。
2. 保留 TopK、summary、制品索引。
3. 记录审计日志，支持回滚窗口（可选）。

---

## 13. Proto 与 API 契约重构计划

### 13.1 Proto 重命名（建议）

1. `Loop*` 保留。
2. `Job*` -> `Round*`。
3. `Task*` -> `Step*`（对外可保留兼容别名一期）。
4. 新增 `DispatchKind` 枚举。
5. 新增 `ActivateSamples` 领域 RPC（替代误导性 `AutoLabel` 命名）。

### 13.2 API 路由语义

1. `/loops/{id}/rounds`
2. `/rounds/{id}/steps`
3. `/steps/{id}/events`
4. `/steps/{id}/artifacts`
5. `/loops/{id}:confirm`（仅 AL）
6. `/loops/{id}/rounds/{round_index}:cleanup-predictions`

---

## 14. 数据库重构计划（语义层）

1. 表重命名
- `loop`（保留）
- `job` -> `round`
- `job_task` -> `step`
- `task_event` -> `step_event`
- `task_metric_point` -> `step_metric_point`

2. 新字段
- `step.dispatch_kind`
- `loop.terminal_reason`
- `round.terminal_reason`
- `round.output_commit_id`
- `step.resolved_params`（强制）

3. 索引
- `round(loop_id, round_index)` unique
- `step(round_id, step_index)` unique
- `step_event(step_id, seq)` unique

---

## 15. 并发与幂等规范

1. per-loop advisory lock：同一 Loop 仅一个编排推进者。
2. dispatch scan lock：同一时刻仅一个实例执行全局派发扫描。
3. 命令幂等：`command_id` 唯一。
4. ORCHESTRATOR Step 幂等：`step_id` + `action_key`。
5. 状态迁移 CAS：所有关键 UPDATE 带前置状态条件。

---

## 16. 验收标准

1. 模式语义
- AL 仅 AL 可 confirm。
- SIM 自动推进，无 confirm。
- MANUAL 单轮即终态。

2. 稳定性
- STOPPING 在 dispatcher 重启后可继续收敛到 STOPPED。
- 无重复 Round。
- 无重复 Step 派发。

3. 可观测
- 漏斗视图完整（Loop -> Round -> Step）。
- 每个 Step 可查看日志、指标、制品、参数。

4. 数据控制
- Cleanup 可按 TTL 自动执行。
- 用户可按轮次触发预测清理。

---

## 17. 实施顺序（建议）

1. PR-A：语义冻结与命名重构设计评审（本文件确认）。
2. PR-B：Proto + DTO 重命名（兼容别名一期）。
3. PR-C：数据库表/字段重命名 + dispatch_kind。
4. PR-D：ModePolicy 落地，ACTIVATE_SAMPLES 改为 ORCHESTRATOR Step。
5. PR-E：STOPPING 恢复扫描与幂等取消。
6. PR-F：日志漏斗前端视图 + SIM 冷却。
7. PR-G：Cleanup（TTL + 按需清理）与审计。

---

## 18. 最终语义判定

1. `Loop / Round / Step` 是最终分层命名。
2. `AUTO_LABEL` 不再作为术语；统一 `ACTIVATE_SAMPLES`。
3. `MANUAL` 的目标是“普通训练单次闭环”，非主动学习流程。
4. `WAIT_USER` 是 Loop 正式 phase，而非隐含在 Round 状态中的临时概念。


# Saki Runtime 语义计划书 v2（Loop / Round / Step）

## 0. 文档定位

本文件是 `saki-api`、`saki-dispatcher`、`saki-executor` 的统一运行时语义基线，覆盖：

1. 用户动作与系统行为。
2. Loop/Round/Step 分层状态机。
3. 三种模式（ACTIVE_LEARNING / SIMULATION / MANUAL）语义。
4. 事件、制品、指标、预测结果与清理策略。
5. 数据一致性、并发与幂等。
6. 命名重构（ALLoop/Job/JobTask -> Loop/Round/Step）落地范围。

本版是强语义版本，不做旧语义兼容。

---

## 1. 总体原则

1. 顶层容器统一命名 `Loop`：实验生命周期容器，不局限主动学习。
2. 第二层统一命名 `Round`：单次迭代上下文。
3. 第三层统一命名 `Step`：最小执行单元。
4. 执行职责分离：
- `DISPATCHABLE` Step 由 executor 执行。
- `ORCHESTRATOR` Step 由 dispatcher 执行。
5. 模式差异通过 `ModePolicy` 注入，不靠散落的 if-else。
6. Loop 进度以 Round 事实为准，不以 `loop.current_round` 单字段作为真值。

---

## 2. 术语与分层

### 2.1 Loop（实验容器）

作用：绑定 branch、保存实验目标、模式、生命周期状态。

关键字段建议：

1. `id`
2. `project_id`
3. `branch_id`
4. `mode`
5. `state`
6. `phase`
7. `max_rounds`
8. `last_confirmed_commit_id`
9. `terminal_reason`
10. `latest_runtime_summary`

### 2.2 Round（单轮上下文）

作用：承载一轮训练/评估/选样/激活的输入输出。

关键字段建议：

1. `id`
2. `loop_id`
3. `round_index`
4. `state`
5. `input_commit_id`
6. `output_commit_id`
7. `summary_metrics`
8. `terminal_reason`

### 2.3 Step（最小逻辑单元）

作用：最小调度与可观测单位。

关键字段建议：

1. `id`
2. `round_id`
3. `step_index`
4. `step_type`
5. `dispatch_kind`（`DISPATCHABLE` / `ORCHESTRATOR`）
6. `state`
7. `depends_on_step_ids`
8. `resolved_params`
9. `assigned_executor_id`
10. `attempt`
11. `dispatch_request_id`
12. `state_version`

---

## 3. 命名重构范围（必须统一）

### 3.1 代码命名

1. `ALLoop` -> `Loop`
2. `Job` -> `Round`
3. `JobTask` -> `Step`
4. `JobStatusV2` -> `RoundStatus`
5. `JobTaskStatus` -> `StepStatus`
6. `JobTaskType` -> `StepType`

### 3.2 数据库对象

1. `loop`（保留表名，不再强调 AL）
2. `job` -> `round`
3. `job_task` -> `step`
4. `task_event` -> `step_event`
5. `task_metric_point` -> `step_metric_point`
6. `task_candidate_item` -> `step_candidate_item`

### 3.3 Proto 契约

1. `job_id` 字段改为 `round_id`
2. `task_id` 字段改为 `step_id`
3. `round_index` 保留
4. `RuntimeTaskType.AUTO_LABEL` 改名为 `ACTIVATE_SAMPLES`（仅语义重命名，行为归 ORCHESTRATOR）

说明：若考虑渐进升级，可在一段窗口内保留字段别名，但最终以新名为唯一语义。

---

## 4. 用户动作模型

### 4.1 Loop 动作

1. `StartLoop`
2. `PauseLoop`
3. `ResumeLoop`
4. `StopLoop`
5. `ConfirmLoop`（仅 AL）

### 4.2 Round / Step 动作

1. `StopRound`
2. `StopStep`
3. `RetryStep`（可选）
4. `TriggerDispatch`

### 4.3 观测动作

1. `GetRuntimeSummary`
2. `ListExecutors`
3. `GetExecutor`
4. `GetLoopView`（Loop + Round + Step 漏斗）

---

## 5. 状态机定义

### 5.1 LoopState

1. `DRAFT`
2. `RUNNING`
3. `PAUSED`
4. `STOPPING`
5. `STOPPED`
6. `COMPLETED`
7. `FAILED`

### 5.2 LoopPhase

#### ACTIVE_LEARNING

1. `AL_BOOTSTRAP`
2. `AL_TRAIN`
3. `AL_SCORE`
4. `AL_SELECT`
5. `AL_WAIT_USER`
6. `AL_EVAL`
7. `AL_FINALIZE`

#### SIMULATION

1. `SIM_BOOTSTRAP`
2. `SIM_TRAIN`
3. `SIM_SCORE`
4. `SIM_SELECT`
5. `SIM_ACTIVATE`
6. `SIM_EVAL`
7. `SIM_FINALIZE`

#### MANUAL

1. `MANUAL_BOOTSTRAP`
2. `MANUAL_TRAIN`
3. `MANUAL_EVAL`
4. `MANUAL_EXPORT`
5. `MANUAL_FINALIZE`

### 5.3 RoundState

1. `PENDING`
2. `RUNNING`
3. `WAIT_USER`
4. `COMPLETED`
5. `CANCELLED`
6. `FAILED`

### 5.4 StepState

1. `PENDING`
2. `READY`
3. `RUNNING`
4. `SUCCEEDED`
5. `FAILED`
6. `CANCELLED`
7. `SKIPPED`

### 5.5 终结原因（TerminalReason）

1. `SUCCESS`
2. `USER_STOP`
3. `SYSTEM_ERROR`
4. `DATA_CONSTRAINT`

---

## 6. 三模式语义

### 6.1 ACTIVE_LEARNING

Round 模板：

1. `TRAIN`（DISPATCHABLE）
2. `SCORE`（DISPATCHABLE）
3. `EVAL`（DISPATCHABLE）
4. `SELECT_TOPK`（ORCHESTRATOR）
5. Round -> `WAIT_USER`

推进规则：

1. 用户补标后调用 `ConfirmLoop` 才可进入下一轮。
2. `ConfirmLoop` 守卫：
- `new_labels_since(last_confirmed_commit_id) > 0`
- 或 `force=true`

### 6.2 SIMULATION（模拟主动学习）

Round 模板：

1. `TRAIN`（DISPATCHABLE）
2. `SCORE`（DISPATCHABLE）
3. `EVAL`（DISPATCHABLE）
4. `SELECT_TOPK`（ORCHESTRATOR）
5. `ACTIVATE_SAMPLES`（ORCHESTRATOR）
6. `ADVANCE_BRANCH`（ORCHESTRATOR）

推进规则：

1. 不需要人工 confirm。
2. 自动迭代直到 `max_rounds`。
3. 加入冷却参数：`SIMULATION_ROUND_COOLDOWN_SEC`（默认 5 秒）。
4. 冷却只影响节奏，不影响结果语义。

### 6.3 MANUAL（普通单次训练）

语义目标：非主动学习的单次训练流程。

Round 模板：

1. `TRAIN`（DISPATCHABLE）
2. `EVAL`（DISPATCHABLE）
3. `EXPORT`（DISPATCHABLE）

推进规则：

1. 默认 `max_rounds=1`。
2. 无 `ConfirmLoop`。
3. 成功即 Loop `COMPLETED`。

---

## 7. 严格转移语义

### 7.1 Loop 转移

1. `DRAFT --start--> RUNNING`
2. `RUNNING --pause--> PAUSED`
3. `PAUSED --resume--> RUNNING`
4. `RUNNING|PAUSED --stop--> STOPPING`
5. `STOPPING --all in-flight step terminal--> STOPPED`
6. `RUNNING --policy completed--> COMPLETED`
7. `RUNNING --unrecoverable error--> FAILED`

### 7.2 STOPPING 可恢复语义

问题：dispatcher 在 `STOPPING` 阶段重启可能中断取消流程。

规范：

1. Tick 必扫 `state=STOPPING` 的 Loop。
2. 对所有 in-flight Step 反复发送 cancel（幂等）。
3. 当所有 in-flight Step 终态后，原子写 `STOPPED`。
4. 若超时，Round 标 `CANCELLED` 并写审计告警。

### 7.3 Round 转移

1. `PENDING -> RUNNING`
2. `RUNNING -> WAIT_USER`（仅 AL）
3. `RUNNING -> COMPLETED`
4. `RUNNING -> CANCELLED`
5. `RUNNING -> FAILED`
6. `WAIT_USER -> RUNNING`（AL confirm 后创建下一轮，当前轮保持终态）

### 7.4 Step 转移

1. `PENDING -> READY`
2. `READY -> RUNNING`
3. `RUNNING -> SUCCEEDED|FAILED|CANCELLED`
4. `FAILED -> READY`（仅在可重试策略下）

---

## 8. ACTIVATE_SAMPLES 事务语义（重点）

说明：此动作不是模型自动画框，而是“从 Oracle 全集向训练可见集激活样本”。

### 8.1 原子性目标

1. 不允许 `SELECT_TOPK` 成功但激活只做一半。
2. 不允许 Branch 已推进但 Round/Step 没记录成功。

### 8.2 幂等键

`activation_key = loop_id + round_index + hash(sample_ids)`

补充约定（双层幂等）：

1. `command_id`：控制面命令幂等键，由 dispatcher 生成并透传，保证命令日志可重放与去重。
2. `activation_key`：业务语义幂等键，由 runtime_domain 根据样本集合计算，保证“同一轮同一样本集合”返回同一 `commit_id`。
3. 两者职责不同，不要求同公式；`command_id` 变化但 `activation_key` 不变时，仍必须命中同一业务结果。

### 8.3 事务边界

1. dispatcher 生成 `ACTIVATE_SAMPLES` step。
2. 调用 `runtime_domain.ActivateSamples`（建议新增 RPC）。
3. runtime_domain 在一个业务事务内执行：
- 样本激活
- 生成 commit
- 推进 branch head
4. 返回 `output_commit_id`。
5. dispatcher 落 Step 结果与 Round `output_commit_id`。

### 8.4 重试要求

同一 `activation_key` 重试必须返回同一 commit 结果。

---

## 9. 并发与一致性

1. 每个 Loop 推进使用 `advisory lock`。
2. 分发扫描使用全局 `dispatch scan lock`。
3. 状态更新使用 CAS（`WHERE state = old_state`）。
4. 命令使用 `command_id` 幂等日志。
5. 事件写入使用 `(step_id, seq)` 幂等约束。
6. `round(loop_id, round_index)` 唯一约束防止重复轮次。
7. `step(round_id, step_index)` 唯一约束防止重复步骤。

---

## 10. 可观测与前端展示语义

### 10.1 漏斗式视图（推荐）

1. Loop 列表展示：总体状态、当前 phase、round 进度。
2. 点击 Loop：展示 Round 列表与每轮 summary metrics。
3. 点击 Round：展示 Step 列表。
4. 点击 Step：展示实时事件流（日志/进度/指标/制品）。

### 10.2 结果与制品

1. Step 级：原始日志、指标点、候选样本、制品 URI。
2. Round 级：聚合指标、混淆矩阵、PR/F1 曲线、选样结果。
3. Loop 级：最佳轮次、最终模型、对比图。

---

## 11. Cleanup 语义（防止膨胀）

### 11.1 自动清理（TTL）

1. `prediction_item`、中间日志按 TTL 清理。
2. 默认保留：
- TopK 候选
- round summary
- 最终制品

### 11.2 按需清理（用户触发）

提供 API：`CleanupRoundPredictions(loop_id, round_index)`

规则：

1. 仅清除可再生的中间预测数据。
2. 不删除：
- TopK 选择结果
- step 终态
- round summary
3. 记录 `cleanup_audit_log`。

---

## 12. 连接与接口

### 12.1 api -> dispatcher（dispatcher_admin）

1. `StartLoop`
2. `PauseLoop`
3. `ResumeLoop`
4. `StopLoop`
5. `ConfirmLoop`
6. `StopRound`
7. `StopStep`
8. `GetRuntimeSummary`
9. `ListExecutors`
10. `TriggerDispatch`

### 12.2 dispatcher -> api（runtime_domain）

1. `GetBranchHead`
2. `CountNewLabelsSinceCommit`
3. `ActivateSamples`（建议新增）
4. `AdvanceBranchHead`

---

## 13. 实施分期（coding-commit-push）

### PR-1 语义与协议落盘

1. 文档与 YAML 状态矩阵。
2. proto 增补（StepDispatchKind / ACTIVATE_SAMPLES / Round/Step 命名）。

### PR-2 dispatcher 状态机落地

1. Loop STOPPING 扫描。
2. SIMULATION 冷却。
3. ACTIVATE_SAMPLES ORCHESTRATOR 步骤。

### PR-3 api 适配

1. 控制面完全走 dispatcher_admin。
2. 观测面对齐 Loop/Round/Step 漏斗语义。

### PR-4 executor 与事件链路

1. runtime_control 字段重命名与兼容。
2. 日志/制品/指标链路验证。

### PR-5 命名重构

1. Python/Go 类名、模块名、表名统一。
2. 前端字段与文案统一。

### PR-6 稳定性与清理

1. 并发压测。
2. Cleanup API + TTL 作业。
3. 端到端验收。

---

## 14. 验收标准

1. 三模式状态机路径可复现，且语义与本文件一致。
2. STOPPING 可在 dispatcher 重启后收敛到 STOPPED。
3. 不重复创建 Round，不重复派发 Step。
4. `ACTIVATE_SAMPLES` 支持幂等重试，且不产生半提交。
5. 前端可按 Loop -> Round -> Step 逐级查看日志与指标。
6. Cleanup 不破坏核心追溯能力。
