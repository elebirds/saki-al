# Saki 重构设计说明

日期：2026-03-16

## 1. 概述

本文档定义 Saki 下一阶段的重构目标架构、语言选择、系统边界、协议治理、运行时高可用方案与迁移路径。

本次重构的首要目标不是短期交付速度，而是长期可维护性、边界清晰度、协议稳定性，以及用更严格的工程约束承载复杂 runtime 与 annotation 领域。

## 2. 现状判断

当前仓库已经具备较清晰的高层角色划分：

- `saki-api`：业务 API 与部分 runtime 领域能力
- `saki-dispatcher`：调度与 executor 接入
- `saki-executor`：执行器宿主
- `saki-plugin-sdk` 与 `saki-plugins/*`：Python 插件体系
- `saki-web`：前端工作台
- `shared/saki-ir` 与 `proto/`：跨语言契约与 IR 规范

但实现层已经出现以下结构性问题：

1. 控制面被错误地物理拆分为 `api + dispatcher` 两个服务，但 runtime 真相没有真正拆开。
2. runtime 关键链路仍存在 `dispatcher -> api runtime-domain` 的同步依赖，导致 API 与调度器无法真正独立演化。
3. Python 控制面在缺少足够强的编译期约束、协议生成与架构守卫时，已经出现大文件聚合、边界漂移与文档漂移。
4. proto 语义并非全错，但存在 `Struct` 使用过多、职责混杂、边界不清的问题，不适合原样冻结。
5. annotation 中存在真正的几何/映射算法模块，不能按普通 CRUD 方式重写。

## 3. 设计目标

本次重构应同时满足以下目标：

1. 建立长期稳定的控制面主干语言与模块边界。
2. 让 `public API` 可独立重启，而运行中的 task 不因 API 重启而中断。
3. 保留 Python 在算法与模型生态中的优势，但不再让它承担系统主干控制面。
4. 将 runtime 编排改造成显式状态机与单 leader 调度模型。
5. 将 annotation geometry 语义与 annotation mapping 算法分层。
6. 保持渐进式迁移，不做一次性大爆炸重写。

## 4. 非目标

以下事项不属于本次重构的第一阶段目标：

- 不追求全面微服务化。
- 不追求第一版就把所有 Python 算法迁移到 Go。
- 不追求原样保留当前 proto wire format。
- 不追求先重写前端框架或改造现有 Web UI 风格。

## 5. 最终架构决策

### 5.1 语言选择

推荐语言分工如下：

- `saki-controlplane`：Go
- `saki-agent`：Go
- `saki-plugin-sdk-py` 与各算法插件：Python
- `saki-web`：TypeScript / React

决策原因：

1. Go 最适合控制面、调度、长连接、gRPC、进程管理、artifact 传输、I/O 编排。
2. Python 最适合模型训练、推理、OpenCV/NumPy、格式转换与插件生态。
3. 将 Python 从控制面降级为算法执行层，可以显著降低长期结构漂移风险。
4. 不采用 `Kotlin Web API + Go controlplane` 双主语言方案，以避免控制面再次出现语言级别的边界分裂。

### 5.2 核心系统形态

推荐将系统收敛为：

- `saki-controlplane`
- `saki-agent`
- `saki-plugin-sdk-py`
- `saki-web`

其中 `saki-controlplane` 是唯一控制面主系统，统一承载业务真相与 runtime 真相。

### 5.3 不做全面微服务化

本次重构不以“拆更多服务”为目标，而以“控制面强模块化 + 执行面独立化”为目标。

原因如下：

1. `project / annotation / runtime / permissions` 当前共享主库、共享事务边界、共享业务不变量，尚未形成可自治的 bounded context。
2. 过早拆分只会把进程内复杂度升级为分布式一致性问题。
3. 当前项目最需要的是硬边界和强约束，而不是更多 RPC。

## 6. Controlplane 边界

### 6.1 必须留在 controlplane 内的模块

以下模块应作为同一控制面核心域存在：

- `identity / access / permissions`
- `project / branch / commit / dataset / sample`
- `annotation / draft / sample-state`
- `runtime-core / loop / round / step / task / prediction`
- `artifact metadata / ticket issuing`
- `system settings / desired state`

保留在同一 controlplane 的根本原因不是“这些模块联系很多”，而是：

1. 它们共享主数据真相。
2. 它们共享事务边界。
3. 它们共享业务不变量。
4. 它们之间的大量命令处理需要同步校验多个领域对象。

### 6.2 未来可拆出的模块

以下模块在边界稳定后可以考虑独立：

- `import-worker`
- `plugin-worker`
- `agent-gateway`
- `analytics / report / search`
- `notification / audit sink`
- `media-processing`

这些模块更偏 I/O、计算、转换、投递或独立伸缩需求，适合最终一致性。

## 7. 运行角色与部署拓扑

### 7.1 Controlplane 内部角色

同一套 `saki-controlplane` 代码中暴露以下 role：

- `public-api role`
- `runtime role`
- `admin role`
- `event-stream role`

这四类 role 可以共进程部署，也可以按部署角色拆成多个进程实例，但它们共享同一控制面领域模型与代码库。

### 7.2 推荐部署拓扑

最终拓扑建议为：

- `N` 个 `public-api`
- `K` 个 `runtime role`
- `M` 个 `saki-agent`
- 若干 `python plugin worker`

其中：

1. `public-api` 无状态，可挂在负载均衡后滚动重启。
2. `runtime role` 可多副本运行，但同一时刻只有一个 leader 执行调度推进。
3. `saki-agent` 按资源能力水平扩展。
4. `python plugin worker` 由 agent 宿主管理，不直接参与控制面真相写入。

### 7.3 API 重启不影响运行中任务

为了满足“API 可重启，运行不中断”，需要满足：

1. executor/agent 只连接 `runtime role`，不依赖 `public-api`。
2. 运行中的 task 所需输入尽量在派发前物化为不可变快照。
3. runtime 关键状态由 `runtime role` 直接写主库。
4. artifact 上传下载票据由 controlplane 自身发放，且不依赖 `public-api` 存活。
5. API 恢复后主要负责查询与命令入口恢复，而不是补 runtime 核心状态真相。

## 8. 单 Leader 调度设计

### 8.1 目标

同一时刻只能有一个 runtime leader 推进 `loop / round / task` 状态机，避免脑裂与重复推进。

### 8.2 方案

不直接实现 Raft/Paxos，而是利用单主数据库作为一致性基础，实现：

- leader lease
- fencing token
- transactional claim
- 幂等调度命令

建议机制：

1. runtime 实例竞争数据库 lease 或 advisory lock。
2. 当选 leader 时拿到递增 `leader_epoch`。
3. 所有调度写入、dispatch 记录、命令执行都带 `leader_epoch`。
4. 旧 epoch 的 leader 即使恢复，也不能再提交有效推进。

### 8.3 设计价值

这套设计与 6.824 中的 leader election / split-brain 思维同类，但工程实现依赖单主数据库，不额外引入独立共识系统，复杂度更适合当前项目阶段。

## 9. 状态机驱动的 Runtime

### 9.1 状态机对象

建议至少显式建模以下状态机：

- `TaskStateMachine`
- `RoundStateMachine`
- `LoopStateMachine`
- 如有必要，增加 `PredictionStateMachine`

### 9.2 实现风格

推荐使用：

- `Command -> DomainEvent -> Evolve(State)` 模型

即：

1. `Decide`：根据当前状态与命令判定能否迁移，并产出领域事件。
2. `Evolve`：根据领域事件演化出新状态。
3. 副作用通过 outbox 或 effect handler 执行，不直接塞进状态迁移器内部。

### 9.3 为什么不是到处 if/else/switch

优雅实现的关键不是“完全没有 switch”，而是：

1. 将状态迁移逻辑限制在小而封闭的状态机对象内。
2. 用显式事件表示“发生了什么”。
3. 将副作用从状态迁移中剥离。
4. 让每个状态机都能被穷举测试。

## 10. 协议治理与 Proto 重构原则

### 10.1 保留什么

保留当前 proto 中沉淀出的核心语义：

- `task`
- `loop / round`
- `executor registration / heartbeat`
- `artifact`
- `metric / log / progress`
- `runtime update`

### 10.2 不保留什么

不原样保留当前 proto 的 wire format，原因包括：

1. `google.protobuf.Struct` 使用过多，弱化了强类型约束。
2. 单个 proto 文件混合了过多职责层级。
3. `runtime_domain` 暴露了过多执行期同步依赖。
4. 一些响应对象偏临时管理接口风格，不适合作为长期冻结契约。

### 10.3 Proto 重构原则

建议将协议重组为更清晰的边界，例如：

- `agent.proto`
- `runtime_events.proto`
- `runtime_admin.proto`
- `artifact.proto`
- `controlplane_commands.proto`

同时遵循以下规则：

1. 核心领域字段尽量强类型化。
2. 仅在插件扩展点保留 `Struct`。
3. 将运行时执行期必须同步调用 controlplane 的接口缩减到最低。
4. 前端和 agent 统一消费生成代码，不再维护手写超大客户端。

## 11. Annotation 语义与 Mapping Engine

### 11.1 语义层

annotation geometry 的真相应继续围绕 `saki-ir` 建立，包括：

- rect / obb 语义
- 几何归一化
- geometry ProtoJSON 编解码
- annotation type 与 geometry shape 一致性校验

这部分属于控制面核心语义，应保持高一致性和高可测试性。

### 11.2 算法层

像 FEDO 双视图映射、查找表投影、OpenCV OBB 拟合这类逻辑，本质上是算法引擎，不应继续埋在 Web API 的业务 service 中。

建议将其重构为独立的 `annotation-mapping-engine`：

- 语言：第一阶段保留 Python
- 能力：NumPy / OpenCV / LUT / 几何拟合
- 输入：源 geometry、样本视图信息、LUT 引用、算法参数
- 输出：标准化后的 `saki-ir Geometry` 列表与诊断信息

### 11.3 为什么第一阶段不迁到 Go

1. 当前算法依赖 NumPy/OpenCV，Python 生态更成熟。
2. 重构的首要目标是收敛系统边界，而不是同时重写成熟算法。
3. 先把算法从业务层剥离并用强类型契约包起来，再决定是否需要语言迁移，风险更低。

## 12. 命名建议

推荐命名：

- `saki-controlplane`
- `saki-agent`
- `saki-plugin-sdk-py`
- `saki-web`

说明：

1. `controlplane` 比 `controlpanel` 更准确，后者更像后台页面。
2. 正式模块名允许略长，优先保证语义准确。
3. 运行时二进制名可以缩短，如 `saki-api`、`saki-runtime`、`saki-agent`。

## 13. 面试可讲的技术亮点

这套方案的亮点不在“服务数量多”，而在工程判断是否成熟。可重点讲以下点：

1. 将错误的 `api + dispatcher` 边界识别并收敛为统一 controlplane。
2. 通过 `public-api role` 与 `runtime role` 分离，实现 API 可重启、运行不中断。
3. 通过多副本 runtime + 单 leader 调度，解决 runtime 脑裂与重复推进问题。
4. 用模块化单体替代伪微服务，避免将单体问题升级为分布式一致性问题。
5. 用 Go 承担 controlplane 与 agent host，用 Python 只承担算法与插件层。
6. 将状态机、outbox、协议生成、强类型边界引入 runtime 核心。
7. 将 annotation geometry 语义层与 annotation mapping 算法层解耦。
8. 采用渐进式迁移路径，而不是一次性大爆炸重写。

## 14. 迁移路径

### 阶段 0：冻结语义基线

目标：

- 冻结 runtime 核心术语与状态语义
- 冻结 `saki-ir` 几何语义
- 列出 proto 重构清单与向后兼容边界

产出：

- runtime 语义说明
- proto 重构草案
- annotation geometry 语义说明

### 阶段 1：搭建新的 Go controlplane 骨架

目标：

- 建立 Go 代码库结构、模块边界、配置体系、repo 层、事务与日志框架
- 先打通 `public-api role` 与 `runtime role` 的最小骨架

### 阶段 2：迁移 runtime 核心链路

目标：

- 优先替换当前 `dispatcher + runtime-domain bridge` 这条最耦合链路
- 落地单 leader 调度、状态机推进、runtime 关键写模型

完成标志：

- 运行中任务不再依赖 API bridge 存活

### 阶段 3：迁移业务 API

建议顺序：

- `access`
- `project`
- `annotation`
- `import orchestration`

### 阶段 4：抽离 annotation mapping engine

目标：

- 将 OpenCV / NumPy / LUT 映射逻辑从控制面业务层移出
- 建立强类型调用契约

### 阶段 5：重写 agent host

目标：

- 将 executor 宿主迁移到 Go
- 保留 Python plugin worker 作为算法执行层

### 阶段 6：清理前端契约层

目标：

- 以生成代码替换手写 API 总网关
- 收敛前端类型与错误模型

## 15. 风险与待确认项

1. runtime 执行前需物化哪些数据快照，需要进一步细化。
2. annotation mapping engine 的调用方式，需要在 `进程内嵌入 / sidecar / 独立 worker` 中明确第一阶段选型。
3. proto 重构时是否保留旧 agent 兼容层，需要结合迁移节奏评估。
4. 主库 schema 在 controlplane 合并后是否立刻重整，需要结合迁移成本决定。

## 16. 最终结论

本次重构的最终建议如下：

1. 主干语言选 Go，Python 保留在插件与算法层。
2. 将 `api + dispatcher` 收敛为统一的 `saki-controlplane`。
3. 在同一 controlplane 内区分 `public-api role` 与 `runtime role`。
4. 部署上采用多副本 API、多副本 runtime 单 leader、多 executor 的拓扑。
5. 不做全面微服务化，先做强模块化 controlplane。
6. 保留 proto 的领域语义，不保留现有 wire format 细节。
7. 将 annotation geometry 真相与 annotation mapping 算法引擎分层。
8. 按阶段渐进迁移，先解决 runtime 核心耦合与可用性问题。
