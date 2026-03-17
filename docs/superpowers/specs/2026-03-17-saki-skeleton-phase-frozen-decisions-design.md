# Saki 骨架期冻结决策设计

日期：2026-03-17

## 1. 文档目的

本文档用于补充 `2026-03-16-saki-rearchitecture-design.md`。

总设计文档回答的是“最终架构要收敛到哪里”；本文档回答的是“在骨架搭建期，哪些边界和契约必须先冻结，哪些空壳状态是允许的”。

本文档的核心目标有三个：

1. 明确骨架期的验收标准不是“功能齐全”，而是“边界稳定、契约一致、后续可安全扩写”。
2. 冻结 `saki-controlplane`、`runtime role`、`saki-agent`、`annotation mapping engine`、`public-api` 的职责边界。
3. 消除当前已经出现的“同一链路上有多套语义”的风险。

## 2. 适用范围与优先级

本文档适用于以下目录与模块：

1. `saki-controlplane/internal/modules/runtime`
2. `saki-controlplane/internal/modules/annotation`
3. `saki-controlplane/internal/modules/system`
4. `saki-controlplane/internal/app/bootstrap`
5. `saki-agent`
6. `saki-plugin-sdk`
7. `saki-mapping-engine`

文档优先级定义如下：

1. `docs/runtime-task-主干最终语义-v4.md` 负责冻结 `task` 主干语义，不得违反。
2. 本文档负责冻结骨架期实现边界、状态语义、RPC 方向、outbox 契约。
3. `docs/superpowers/specs/2026-03-16-saki-rearchitecture-design.md` 负责给出最终目标架构。
4. `docs/superpowers/plans/*.md` 负责分解任务，不得反向修改这里的冻结决策。

如果计划文档、占位代码或测试样板与本文档冲突，以本文档为准；如果本文档与 `runtime-task-主干最终语义-v4.md` 冲突，视为本文档错误，必须先修文档后修代码。

## 3. 骨架期定义

### 3.1 什么是“骨架期”

骨架期是一个明确阶段，不是“尚未完成的实现残余”。

本文档中的“骨架期”不是 `2026-03-16-saki-rearchitecture-design.md` 里“阶段 1”的同义词。

本文档使用“骨架期”一词，指的是从 foundation skeleton 建立完成，到 runtime 核心链路进入可持续扩写前的“架构冻结窗口”。它覆盖：

1. 总设计文档中的阶段 1：controlplane foundation。
2. 阶段 2 启动前必须先冻结的 runtime 核心契约。

骨架期允许以下状态存在：

1. role 已分离，但具体 handler/effect 仍是空壳。
2. repo、effect、scan、projector 只有接口或最小 no-op 实现。
3. 某些模块只有最小 healthz server、占位 wiring、假 client、测试桩。
4. `Loop / Round / Step` 的持久化与读模型尚未完整落地。

骨架期不允许以下状态存在：

1. 同一链路中数据库、状态机、RPC、effect 使用不同状态集合。
2. 同一字段承担两种职责，例如把 leader 身份和 agent 身份都塞进 `claimed_by`。
3. `public-api`、`runtime role`、`agent`、`mapping engine` 之间职责漂移。
4. 先用“临时实现”绕过状态机，后续再补回正式链路。

### 3.2 骨架期的验收标准

骨架期完成不以“模块是否功能丰富”为标准，而以以下条件为标准：

1. 每条核心跨进程链路都只有一套正式语义。
2. `runtime` 相关写路径都已经落在正确的 role 和边界上。
3. 空壳模块的职责已经固定，后续只允许“补实现”，不允许再改边界。
4. 进入下一阶段后，不需要回头重写 role 拆分、RPC 方向、状态机状态集合和 outbox schema。

## 4. 系统级冻结决策

### 4.1 控制面主系统

冻结决策如下：

1. `saki-controlplane` 是唯一控制面主系统。
2. `public-api role`、`runtime role`、`event-stream role`、`admin role` 是同一代码库内的不同部署角色，不是不同真相源。
3. 不再设计新的 `api + dispatcher` 双主系统边界。

### 4.2 角色职责

`public-api role` 负责：

1. 面向浏览器和用户态命令的 HTTP API。
2. 只读查询和用户态命令入口。
3. 已迁移模块的 repo-backed handler 装配。

`runtime role` 负责：

1. leader lease 竞争与续租。
2. runtime scheduler。
3. runtime command handler。
4. agent ingress。
5. runtime outbox 消费与 side effect 执行。
6. 运行中任务所需的 runtime 关键写路径。
7. 运行中任务所需的 artifact/ticket 等控制面内部服务调用，不依赖 `public-api role` 存活。

`event-stream role` 负责：

1. 对外流式推送 runtime 事件。
2. 只读推送，不拥有 runtime 真相。

`admin role` 负责：

1. 暴露管理查询与受控命令入口。
2. 在骨架期内可与 `public-api role` 共进程。

### 4.3 允许的空壳

在不违反前述职责的前提下，以下空壳是允许的：

1. `runtime` 的 read-model projector、stream broadcaster、retry worker。
2. `LoopRepo`、`RoundRepo`、`Step` 投影相关 repo。
3. `event-stream role` 的完整推送实现。
4. `agent` 的 warm worker、worker pool、复杂资源隔离。
5. `annotation` 的完整 draft/version chain。
6. `public-api` 中尚未迁移的非关键业务 endpoint。

## 5. Runtime 冻结决策

### 5.1 真相源

冻结决策如下：

1. 执行真相源统一为 `task`。
2. `Loop / Round / Step` 是编排与投影视图，不是执行真相源。
3. `Prediction` 是循环外独立资源，执行状态仍挂在 `task`。
4. 任何运行时事件、指标、候选、结果、派发都必须以 `task_id` 为主干标识。
5. `step.task_id -> task.id` 的绑定关系固定为 1:1。
6. 缺失 step-task 投影属于数据错误，派发侧必须失败并记录错误，而不是静默跳过或回退到旧语义。

### 5.2 Task 正式状态集合

骨架期正式冻结以下状态集合：

1. `pending`
2. `assigned`
3. `running`
4. `cancel_requested`
5. `succeeded`
6. `failed`
7. `canceled`

额外约束如下：

1. 不再使用新的未登记中间状态。
2. 当前代码或 SQL 中出现的 `dispatching` 视为骨架期原型名，正式状态名统一替换为 `assigned`。
3. 数据库枚举、状态机、command handler、测试、管理查询必须使用同一集合。

### 5.3 Task 状态语义

`pending` 的语义：

1. 任务已创建。
2. 尚未形成当前执行实例。
3. 可被 scheduler 扫描并参与分配。

`assigned` 的语义：

1. `runtime role` 已为该任务生成新的 `execution_id`。
2. 任务已绑定目标 `agent_id`。
3. 对应的 dispatch outbox 已经写入。
4. agent 可能尚未真正开始执行。

`running` 的语义：

1. agent 已针对当前 `execution_id` 报告开始执行。
2. 运行时日志、进度、指标、结果都归属于当前 `execution_id`。

`cancel_requested` 的语义：

1. 对当前 `execution_id` 的停止请求已生效。
2. 对应 stop outbox 已经写入。
3. 该状态不是终态。

`succeeded`、`failed`、`canceled` 的语义：

1. 都是终态。
2. 终态只由当前 `execution_id` 的合法 terminal event 决定。
3. 旧 `execution_id` 上报的 terminal event 必须被忽略。

### 5.4 Task 合法迁移

先冻结以下主线迁移：

1. `pending -> assigned`
2. `assigned -> running`
3. `pending -> canceled`
4. `assigned -> cancel_requested`
5. `running -> cancel_requested`
6. `running -> succeeded`
7. `running -> failed`
8. `cancel_requested -> canceled`
9. `cancel_requested -> succeeded`
10. `cancel_requested -> failed`

解释如下：

1. `cancel_requested` 表示“控制面已经发出停止意图”，不是“任务必然取消成功”。
2. 如果停止请求发出后，agent 先上报 `succeeded` 或 `failed`，则以当前 `execution_id` 的真实 terminal event 为准。
3. skeleton 阶段允许尚未实现全部迁移。
4. recovery 相关迁移，例如 `assigned -> pending`、`assigned -> failed`，后续必须通过单独 recovery 设计补充后才能实现。

### 5.5 Execution Identity

冻结以下执行实例语义：

1. 每次 `pending -> assigned` 都必须生成新的 `execution_id`。
2. `execution_id` 是一次具体执行尝试的唯一标识。
3. 所有 dispatch、stop、task event、artifact/result 绑定都必须带 `execution_id`。
4. agent 回传事件时，`task_id` 和 `execution_id` 必须同时校验。
5. `execution_id` 不匹配当前任务记录时，该事件必须视为过期事件并被忽略。

### 5.6 Leader Epoch 与 Fencing

冻结以下 leader 语义：

1. `leader_epoch` 来自 `runtime_lease`。
2. 只有 scheduler/command 驱动的 leader-owned 写入必须携带 `leader_epoch`。
3. agent 上报事件不使用 `leader_epoch` 决定合法性，而是使用 `execution_id` 决定。
4. 旧 `leader_epoch` 的 leader 恢复后，不得继续提交新的 assignment、stop 或 recovery 推进。

### 5.7 Runtime 调度链路

冻结唯一合法链路如下：

```text
scheduler scan
  -> command handler
  -> repo / tx
  -> runtime outbox
  -> effect worker
  -> agent rpc / stream / read model
```

额外约束如下：

1. `scheduler` 只负责发现“该发什么 command”。
2. `scheduler` 不得直接改表。
3. `effect` 不得自行决定领域状态迁移。
4. `public-api` 不得直接替代 scheduler 或 effect 做 runtime 写操作。

### 5.8 Repo 与 SQL 的职责

冻结以下原则：

1. SQL 可以为了原子性把 `select + update` 合并为单条语句。
2. 但 SQL 不得引入状态机里不存在的状态。
3. repo 接口可以暂时不完整，但已经存在的接口命名必须表达真实职责。
4. 不得继续使用模糊命名，例如 `claimed_by` 同时表达“leader 抢占者”和“目标 agent”。

字段语义冻结如下：

1. `agent_id` 表示目标执行宿主。
2. `execution_id` 表示当前执行实例。
3. `leader_epoch` 表示创建该 assignment 的 leader 纪元。
4. 不再把 runtime leader 身份持久化为 task 领域字段。

`runtime_task` 在骨架期必须至少承载以下字段语义：

1. `id`
2. `task_kind`
3. `task_type`
4. `status`
5. `current_execution_id`
6. `assigned_agent_id`
7. `attempt`
8. `max_attempts`
9. `resolved_params`
10. `depends_on_task_ids`
11. `leader_epoch`
12. `created_at`
13. `updated_at`

说明如下：

1. 物理列名可按迁移计划调整。
2. 但这些语义不得在骨架期被删除或拆散到不相关表中。

### 5.9 Runtime Outbox 正式定位

冻结如下：

1. `runtime_outbox` 是 runtime 侧主动发起的 effect queue，不是通用日志表。
2. 凡是由 `runtime role` 主动发起、需要重试/去重的异步副作用，都必须通过 outbox 驱动。
3. `assign task` 与 `stop task` 属于必须走 outbox 的 effect。
4. `Register`、`Heartbeat`、`PushTaskEvent` 属于 `agent -> runtime` 直接 ingress RPC，不通过 outbox 进入控制面。
5. projector/stream 也可复用 outbox，但其缺失不阻塞骨架期完成。

### 5.10 Runtime Outbox 最小 schema

骨架期正式冻结以下最小字段语义：

1. `id`
2. `topic`
3. `aggregate_type`
4. `aggregate_id`
5. `idempotency_key`
6. `payload`
7. `available_at`
8. `attempt_count`
9. `published_at`
10. `last_error`

说明如下：

1. 当前实现若字段尚未齐全，视为待补实现，不视为边界未定。
2. 但后续扩写不得绕过 `idempotency_key`、`attempt_count`、`published_at` 这些职责。

### 5.11 Outbox Topic 正式冻结

骨架期只冻结以下必须 topic：

1. `runtime.task.assign.v1`
2. `runtime.task.stop.v1`

如果后续需要 projector 或 stream 相关 topic，可增补，但不得修改前两者语义。

### 5.12 Assign Outbox Payload

`runtime.task.assign.v1` 的 payload 正式冻结如下：

```json
{
  "task_id": "uuid",
  "execution_id": "string",
  "agent_id": "string",
  "task_kind": "STEP|PREDICTION",
  "task_type": "string",
  "attempt": 1,
  "max_attempts": 1,
  "resolved_params": {},
  "depends_on_task_ids": [],
  "leader_epoch": 1
}
```

约束如下：

1. producer 和 consumer 必须共享同一 payload 结构。
2. 不允许 producer 只写 `task_id/claimed_by/leader_epoch`，而 consumer 期待 `execution_id/task_type/payload`。
3. `resolved_params` 可以为空，但字段语义不能缺席。

### 5.13 Stop Outbox Payload

`runtime.task.stop.v1` 的 payload 正式冻结如下：

```json
{
  "task_id": "uuid",
  "execution_id": "string",
  "agent_id": "string",
  "reason": "string",
  "leader_epoch": 1
}
```

### 5.14 Task 观测数据归宿

冻结如下：

1. `task_event`
2. `task_metric_point`
3. `task_candidate_item`

这三类数据都属于 runtime 自有数据模型，必须以 `task_id + execution_id` 为主归属。

骨架期允许：

1. 表结构未完全落地。
2. ingress 先只处理最小事件子集。

骨架期不允许：

1. 未来再回到 `step_id` 主干。
2. 把日志/指标/结果直接散落在不带 `execution_id` 的临时表中。

## 6. Runtime 与 Agent 的 RPC 边界

### 6.1 方向冻结

冻结如下：

1. `agent -> controlplane(runtime role)` 是 ingress。
2. `controlplane(runtime role) -> agent` 是 control。
3. 两个方向不得再放进同一个语义模糊的 server 角色中。

### 6.2 服务拆分

正式冻结为两类服务：

1. `AgentIngress`
2. `AgentControl`

`AgentIngress` 由 `runtime role` 提供，负责：

1. `Register`
2. `Heartbeat`
3. `PushTaskEvent`
4. 后续如有需要，再增补 runtime 侧上报接口

`AgentControl` 由 `agent` 提供，负责：

1. `AssignTask`
2. `StopTask`

说明如下：

1. 文件名可以后续再整理。
2. 但服务方向和方法归属从本文档生效后即视为冻结。
3. `artifact ticket`、`runtime update command` 仍属于 Runtime/Agent RPC 合同，但其具体 service/method 挂点在骨架期暂不冻结。

### 6.3 Register 与 Heartbeat 语义

冻结如下：

1. 注册与心跳的对端进程是 `agent`，不再使用新的 `executor` 名义扩写控制面代码。
2. `runtime_executor` 这类历史命名在骨架期可作为过渡 alias 存在。
3. 新代码、新 proto、新配置、新日志字段一律优先使用 `agent`。

### 6.4 Task Event 语义

骨架期冻结最小 phase 集合：

1. `RUNNING`
2. `SUCCEEDED`
3. `FAILED`
4. `CANCELED`

骨架期冻结最小 payload 类别：

1. `log`
2. `progress`
3. `result`

额外约束如下：

1. `RUNNING`、`SUCCEEDED`、`FAILED`、`CANCELED` 都必须带 `execution_id`。
2. `RUNNING` 必须把任务从 `assigned` 推进到 `running`。
3. 即使 skeleton 期暂未消费全部 payload，协议仍先冻结。

## 7. Agent 冻结决策

### 7.1 Agent 的正式职责

冻结如下：

1. `saki-agent` 是 runtime 的唯一远程执行宿主。
2. agent 主动连接 `runtime role`。
3. agent 负责本地 workspace、cache、artifact、worker 生命周期。
4. agent 不直接写控制面主库。
5. agent 不直接拥有业务真相。

### 7.2 Worker 模型

冻结如下：

1. Python plugin worker 只负责算法执行。
2. worker 不直接连接 controlplane。
3. worker 不直接操作业务数据库。
4. worker 与 agent 之间使用本地 `worker proto`。

### 7.3 生命周期策略

骨架期正式冻结如下：

1. 默认只支持 `ephemeral worker`。
2. `warm worker`、`worker pool`、复杂并发调度都明确后置。
3. 后续扩容只能在不改变前两条边界的前提下进行。

### 7.4 本地执行状态

冻结如下：

1. agent 可在内存中维护当前执行注册表。
2. 骨架期不要求 agent 本地持久化重启恢复。
3. 运行中断后的收敛由 `runtime role + execution_id + recovery scan` 负责，不由 agent 本地持久化承担。

## 8. Annotation 与 Mapping Engine 冻结决策

### 8.1 语义边界

冻结如下：

1. annotation geometry 真相属于 controlplane。
2. mapping、投影、拟合等算法性处理属于 `annotation mapping engine`。
3. mapping engine 不是 runtime 插件，不属于 agent 执行面。

### 8.2 宿主位置

冻结如下：

1. `annotation mapping engine` 作为 controlplane 本地 sidecar / 子进程运行。
2. 不嵌入 controlplane 主进程。
3. 不迁入 `saki-agent`。
4. 不走 runtime task/agent 调度链路。

### 8.3 协议边界

冻结如下：

1. controlplane 与 mapping engine 使用 `worker proto` 风格的本地 framed 协议。
2. 传输对象必须是面向语义的 mapping request/response。
3. 不得把数据库 row、HTTP DTO 或 handler 内部对象直接传给 sidecar。
4. sidecar 的输入输出必须对齐 `saki-ir` 几何语义，而不是对齐临时 controller 结构。

### 8.4 Annotation 最小闭环

冻结如下：

1. 第一版 annotation 创建路径采用强一致。
2. source annotation 与 generated annotation 要么一起成功，要么一起失败。
3. 在 annotation outbox/workflow 真正设计前，不引入部分成功语义。

### 8.5 骨架期允许的空壳

允许如下：

1. `annotation` 的完整 draft/version chain 尚未实现。
2. 只有 `sample/annotation` 最小切片设计或局部 repo。
3. sidecar client 已就位，但完整 API 尚未做实。

不允许如下：

1. 为了省事把 mapping 重新塞回 HTTP handler/service。
2. 为了复用 runtime 链路把 mapping engine 挂到 agent。

## 9. Public API 冻结决策

### 9.1 角色定位

冻结如下：

1. `public-api` 是用户态 facade。
2. `public-api` 自身不拥有 runtime 真相。
3. `public-api` 对 runtime 的任何写操作都必须进入 runtime app command/use case。

### 9.2 Runtime 写边界

冻结如下：

1. `cancel task` 必须走 runtime command handler。
2. `public-api` 不得直接 update `runtime_task`。
3. `public-api` 不得绕过 outbox 直接下发 assign/stop。
4. `public-api` 不得接管 leader lease、scheduler、recovery。

### 9.3 In-memory 实现的限制

冻结如下：

1. 已经声明迁移到 controlplane 正式模型的模块，不允许继续扩写新的 MemoryStore 语义。
2. 尚未开始迁移的模块，可保留 disabled handler、stub handler 或显式 `not implemented`。
3. 不再允许用 MemoryStore 模拟新的 runtime 真相或 annotation 真相。

### 9.4 Import / Export 的边界

冻结如下：

1. `import/export` 不属于当前 runtime-core 骨架收口范围。
2. `import/export` 不得倒逼 runtime task 主干语义改变。
3. 若需要异步 import task，可保留模块内自有任务模型。
4. 在明确设计前，不将 import task 强行并入 runtime task。

## 10. 命名冻结决策

冻结如下：

1. 新架构中的远程执行宿主统一命名为 `agent`。
2. `executor` 仅作为历史兼容 alias 允许短期存在。
3. 自本文档生效后，`saki-controlplane` 与 `saki-agent` 中不得新增新的 `executor` 主命名。

补充说明：

1. 已有公开 HTTP 路径、旧表名、旧环境变量如果暂未迁移，可作为兼容层保留。
2. 但任何新字段、新接口、新日志键、新 proto 字段都应优先使用 `agent`。

## 11. 明确禁止的反模式

自本文档生效后，以下做法视为方向错误，而不是“临时实现”：

1. 在 SQL 中引入状态机未定义的状态。
2. 在 command handler 和 effect 中定义不同的 outbox payload 结构。
3. 用同一个 RPC service 同时承载 `agent -> controlplane` 和 `controlplane -> agent` 的 server 责任。
4. 让 `public-api` 直接改 runtime 表来“先跑通”。
5. 把 leader 身份持久化成 task 领域字段。
6. 把目标执行宿主和调度抢占者混用一个字段表示。
7. 把 mapping engine 重新放回 handler、主进程或 agent。
8. 在新代码里继续扩写新的 `executor` 主命名。

## 12. 进入可持续扩写阶段的退出条件

本节不是总设计文档“阶段 1 完成条件”的定义。

本节定义的是：从“架构冻结窗口”进入“runtime 核心可持续扩写阶段”之前，必须满足的退出条件。

只有满足以下条件，才允许声明“runtime 骨架已经收口，可以进入可持续扩写阶段”：

1. `runtime role` 不再只是 `healthz` server，而是已经实际装配：
   - leader lease loop
   - 至少一个 scheduler scan
   - runtime ingress
   - runtime outbox worker
2. `task` 状态集合在 SQL、状态机、handler、测试中完全一致。
3. `AssignTask` 链路至少存在一条端到端主线回归，覆盖：
   - pending task
   - assign command
   - assign outbox
   - control rpc
   - running event
   - 任一终态事件
4. `execution_id` 已被真正用于事件合法性判定。
5. `public-api -> runtime cancel` 已经过正式 command/outbox 路径。
6. `AgentIngress` 与 `AgentControl` 的方向已经在生成代码和 wiring 中体现。

## 13. 后置而未冻结的细节

以下事项明确后置，但不影响本文档生效：

1. `Loop / Round / Step` 的完整持久化表设计。
2. runtime recovery scan 的完整重试和回收策略。
3. outbox 消费 worker 的批量化和并发模型。
4. artifact ticket 的具体接口与传输细节。
5. event-stream 对外订阅协议。
6. `warm worker`、`worker pool` 的资源治理细节。
7. annotation draft/version chain 的完整数据模型。

这些事项后续可以单独定稿，但不得违反本文档已经冻结的边界与术语。

## 14. 最终结论

骨架期的正确目标不是“尽快把壳子补满”，而是先把最贵的结构性决策锁死。

自本文档生效后，Saki 重构在骨架期的正式方向定义如下：

1. `saki-controlplane` 是唯一控制面主系统。
2. `runtime role` 是 runtime 真相与调度推进的拥有者。
3. `task` 是执行真相主干，`execution_id` 是一次具体执行的唯一标识。
4. `assigned` 取代原型状态名 `dispatching`，成为正式 assignment 状态。
5. runtime 主动发起的异步副作用统一走 outbox，而 `agent -> runtime` ingress 走直接 RPC。
6. `AgentIngress` 与 `AgentControl` 双向 RPC 边界正式分离。
7. `saki-agent` 是唯一远程执行宿主，Python worker 只是本地算法执行层。
8. `annotation mapping engine` 是 controlplane 本地 sidecar，不进入 agent，不嵌入主进程。
9. `public-api` 只作为 facade，不得绕过 runtime 正式写路径。
10. 骨架期允许大量空壳，但不允许任何核心契约继续漂移。
