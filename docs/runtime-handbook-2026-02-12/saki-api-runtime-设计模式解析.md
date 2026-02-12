# Saki API Runtime 设计模式解析（Loop/Job/Task）

> 版本基线：基于当前仓库 `saki-api/src/saki_api` runtime 实现（2026-02-12）
> 目标：从“架构与模式”角度，解释主动学习运行时如何组织与推进。

## 1. 先给结论：这是一个“编排器 + 调度器 + 双向控制流”的分层系统

`runtime` 在 API 侧不是单体流程函数，而是分成了四个角色：

1. `Loop Orchestrator`（编排器）：决定“下一步该做什么”。
2. `Runtime Dispatcher`（调度器）：决定“给谁做”。
3. `RuntimeControlService`（控制面网关）：负责“和执行器说话并落库”。
4. `JobService/ModelService`（领域服务）：负责“业务规则与持久化对象组装”。

这四层通过明确的表模型（`loop/job/job_task/task_event/task_metric_point/task_candidate_item`）串起来，形成可观测、可恢复的控制闭环。

---

## 2. 主要设计模式映射

## 2.1 策略模式（Strategy）：按 Loop Mode 分支，不靠 if-else 巨石函数

代码位置：
- `saki-api/src/saki_api/services/runtime/loop_orchestrator.py`
- `LoopModePolicy`、`ActiveLearningModePolicy`、`SimulationModePolicy`、`ManualModePolicy`

核心思想：
- 终态决策通过 `policy.on_terminal(loop, sim_finished)` 返回 `LoopTerminalDecision`。
- 编排器只执行决策，不内嵌所有模式细节。

收益：
- `active_learning/simulation/manual` 的终态推进规则解耦。
- 后续新增 mode 不需要改主循环主干。

---

## 2.2 状态机模式（State Machine）：Loop/Job/Task 三层状态分离

代码位置：
- `saki-api/src/saki_api/models/enums.py`

分层状态语义：
1. Loop 生命周期状态：`ALLoopStatus`（DRAFT/RUNNING/PAUSED/STOPPED/COMPLETED/FAILED）
2. Loop 相位状态：`LoopPhase`（按 mode 分组）
3. Job 聚合状态：`JobStatusV2`
4. Task 执行状态：`JobTaskStatus`

这是一种“控制状态”与“执行状态”解耦的典型状态机分层：
- Loop 关注过程与阶段。
- Task 关注机器执行细节。
- Job 只做聚合，不承担具体执行。

---

## 2.3 管道模式（Pipeline）：Task 串联而非 Job 巨流程

代码位置：
- `saki-api/src/saki_api/services/runtime/job.py` 中 `create_next_job_with_tasks`

做法：
- 每轮创建 `Job` 后，按 mode 生成有序 `JobTask` 链。
- 依赖通过 `depends_on` 建立。
- 调度器只派发“依赖满足”的 Task。

这让每个步骤天然可重试、可观测、可替换。

---

## 2.4 仓储模式（Repository）+ 应用服务模式（Service）

代码位置：
- `repositories/runtime/*.py`
- `services/runtime/*.py`

意图：
- 仓储负责查询与更新。
- 服务负责规则与编排语义。

当前现实：
- 大多数业务路径已通过仓储封装；
- 但 `dispatcher/runtime_control` 仍保留直接 `SessionLocal` + `session.get/select` 的数据访问（偏基础设施层直写）。

---

## 2.5 适配器模式（Adapter）：Proto 与域对象解耦

代码位置：
- `saki-api/src/saki_api/grpc/runtime_codec.py`

做法：
- `build_*` / `parse_*` / `decode_task_event` 统一处理 proto 与 dict/Struct 的转换。
- gRPC 消息细节不直接散落到业务代码。

价值：
- 协议升级时，影响面集中在 codec。

---

## 2.6 生产者-消费者模式（Producer-Consumer）：任务入队与派发

代码位置：
- `saki-api/src/saki_api/grpc/dispatcher.py`

机制：
- 生产者：`loop_orchestrator` 在建任务后 `enqueue_task`。
- 消费者：`dispatch_pending_tasks` 按 executor 可用性消费队列。
- 内部结构：`asyncio.Queue` + `_queued_task_ids` 去重。

---

## 2.7 事件溯源风格（Event-Carried State Transfer）

代码位置：
- 事件落库：`RuntimeControlService._persist_task_event`
- 结果落库：`RuntimeControlService._persist_task_result`
- 事件模型：`models/runtime/task_event.py`

说明：
- Task 实时事件（status/log/progress/metric/artifact）先持久化为事件流。
- 同时更新 Task/Job 聚合字段，兼顾“可回放”与“快速查询”。

---

## 3. 从创建 AL Loop 到流程结束：模式级全过程

```mermaid
flowchart TD
    A[创建 Loop<br/>POST /projects/{id}/loops] --> B[Loop DRAFT]
    B --> C[启动 Loop<br/>POST /loops/{id}:start]
    C --> D[Orchestrator Tick]
    D --> E[创建 Job + Task 链]
    E --> F[Dispatcher 派发首个可执行 Task]
    F --> G[Executor 执行并回传 Event/Result]
    G --> H[API 落库并聚合 Job 状态]
    H --> I{当前 Job 终态?}
    I -- 否 --> F
    I -- 是 --> J{ModePolicy 决策}
    J -- create_next_job --> D
    J -- complete/fail --> K[Loop 终态]
```

要点：
1. 编排器只负责“下一步业务动作”；
2. 调度器只负责“派发与 ACK 超时恢复”；
3. 控制面只负责“通信协议 + 状态落库”；
4. 终态判定通过 mode policy 完成。

---

## 4. 调度与任务分配：模式层视角

## 4.1 调度触发源

1. 周期触发：`LoopOrchestrator._run`（interval，最小 2 秒）
2. 控制面触发：`start/resume/confirm` 后调用 `tick_once`
3. Job API 触发：创建 job 后立即 `dispatch_pending_tasks`

## 4.2 分配算法（简化）

1. 读取 Task payload（plugin/mode/params/deps 等）。
2. 选 executor：在线、非 busy、插件可匹配、可选 allowlist。
3. DB 将 Task 标记 `DISPATCHING`，Job 标记 `JOB_RUNNING`。
4. 下发 `AssignTask`。
5. 等待 ACK：
   - `OK` -> Task `RUNNING`
   - `ERROR` 或超时 -> Task 回 `PENDING` 并重入队

## 4.3 依赖门禁

`_pending_dispatch_tasks` 只放行依赖任务全部 `SUCCEEDED` 的 Task。

---

## 5. 插件能力如何进入 API 决策

## 5.1 能力注册

- executor 注册时上报 `PluginCapability`（plugin_id、task_types、strategies、schema、默认配置、accelerator）。
- dispatcher 落库到 `runtime_executor.plugin_ids`。

## 5.2 能力消费

- `JobService._validate_plugin_id` 会从在线 executor 能力目录抽取 plugin_id 做合法性检查。
- 运行时插件目录由 `runtime_plugin_catalog.aggregate_runtime_plugins` 聚合，提供冲突检测（同 plugin_id 不同 schema/能力）。

---

## 6. 关键模式的边界是否清晰？

结论：中上，但仍有基础设施层可继续收敛。

优点：
1. Loop policy 已策略化。
2. Job/Task 语义清晰。
3. 事件与结果链路闭环。

不足：
1. `dispatcher/runtime_control` 仍有较多直接 SQLModel 访问，仓储抽象不完全。
2. 调度与编排使用进程内内存结构（session/pending 队列）作为关键控制状态，多实例扩展边界弱。
3. payload 在 API 内仍大量以 `dict` 传输，DTO 化还可继续推进。

---

## 7. 当前实现里“模式层”最容易出问题的点（你可重点审查）

1. 多实例一致性
- `RuntimeDispatcher` 的 `_sessions/_pending_assign/_task_queue` 是进程内状态。
- 若 API 多实例，需外置一致性层（Redis/DB 锁/MQ）。

2. 统计快照落库链路不完整
- 有 `runtime_executor_stats` 模型与查询 API，但当前未见定时写入路径。

3. 依赖字段类型
- `JobTask.depends_on` 当前是 `List[str]`，而非强类型 UUID 列表；解析容错高但约束弱。

4. 编排与聚合函数重复
- Job 聚合逻辑在 `loop_orchestrator` 与 `runtime_control` 各有一版，存在演化漂移风险。

---

## 8. 你如果要继续重构（模式优先顺序）

1. 先统一状态聚合器（单一实现，orchestrator/control 共用）。
2. 再将 dispatcher/runtime_control 的 DB 访问收敛到 repository/service。
3. 再做 payload DTO 化（替代关键 dict）。
4. 最后做多实例化改造（锁、队列、幂等中心）。

---

## 9. 一句话总结

`Saki API runtime` 当前已经是“模式可读”的架构：
- 用 `LoopModePolicy` 做编排决策，
- 用 `Job/Task` 拆执行语义，
- 用 `Dispatcher + RuntimeControl` 解耦派发与协议，
- 但在“多实例一致性、DTO 强类型、聚合器唯一化”上仍有下一阶段工程化空间。
