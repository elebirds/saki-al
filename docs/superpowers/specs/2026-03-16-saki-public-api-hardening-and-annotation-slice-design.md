# Saki Public API 落实与 Annotation 最小闭环设计

日期：2026-03-16

## 1. 目标

本文档定义 `saki-controlplane` 下一阶段的两个连续里程碑：

1. 将现有 `public-api` 从演示骨架改造成真实控制面接口。
2. 在此基础上落地 `annotation` 的最小纵向闭环，并接入已完成的本地 mapping sidecar。

本阶段的核心目标是减少返工，而不是尽快铺出更多 endpoint。

## 2. 现状

当前 `saki-controlplane` 已具备：

- `public-api` 基础骨架与 OpenAPI 合同
- `runtime` 状态机、repo、scheduler、internal RPC
- `agent` 与 Python worker 协议
- `annotation mapping engine` 的本地 sidecar 调用链路

但仍存在以下问题：

1. `public-api` 仍在使用内存实现与硬编码装配。
2. `project`、`runtime-admin` 虽然已有 HTTP 接口，但尚未全部接到真实 repo / DB。
3. `annotation` 只有 sidecar，没有新的 controlplane 领域模型、持久化和 API。
4. `import/export` 尚未迁移，且缺少 `sample / annotation` 这些新的落库归宿。

## 3. 设计原则

本阶段遵循以下原则：

1. 优先把已暴露的合同做实，而不是继续铺口子。
2. 新增能力采用纵向切片：`schema -> repo -> app -> api -> test`。
3. `runtime` 命令必须经过状态机与 outbox，不允许 public-api 绕过状态机直接改表。
4. `annotation` 第一版采用强一致写路径，不做部分成功语义。
5. `import/export` 暂缓，等待 `sample / annotation / mapping` 归宿稳定后再接入。

## 4. 里程碑 A：现有 Public API 做实

### 4.1 范围

本里程碑只覆盖三类已存在接口：

- `access`
- `project`
- `runtime-admin`

### 4.2 模块边界

#### `system/bootstrap`

当前 `public-api` server 仍在直接构造：

- `Authenticator`
- `MemoryStore`
- `MemoryAdminStore`

这一层必须改成真正的装配入口：

- `bootstrap` 负责 `config / logger / db / repo / app / handler` 的依赖装配
- `apihttp` 只接收依赖，不在 handler 内部自行 new store
- `public-api` 与 `runtime` 共用统一的配置与基础设施

#### `access`

本阶段不构建完整 RBAC 或资源权限模型，只做正式 bootstrap auth：

- 将 HMAC secret、TTL 从硬编码迁到配置
- 保留现有 `login / me / permission-check` 合同
- 不在这一阶段引入复杂 `resource_member / role` 表

这一步的目标是去演示化，而不是完成最终身份系统。

#### `project`

`project` 必须彻底从 `MemoryStore` 切换到真实 repo。

建议表结构至少包含：

- `id`
- `name`
- `created_at`
- `updated_at`

现有 API 路径保持不变：

- `POST /projects`
- `GET /projects`
- `GET /projects/{project_id}`

#### `runtime-admin`

`runtime-admin` 从 `MemoryAdminStore` 切换到真实读模型与命令处理。

建议新增或补齐：

- `runtime_executor`
  - `id`
  - `version`
  - `status`
  - `last_seen_at`
  - `capabilities jsonb`
  - `created_at`
  - `updated_at`

现有接口继续保留：

- `GET /runtime/summary`
- `GET /runtime/executors`
- `POST /runtime/tasks/{task_id}/cancel`

其中：

- `summary` 从 `runtime_task + runtime_lease (+ runtime_executor)` 聚合
- `executors` 从 `runtime_executor` 读取
- `cancel task` 必须走已有 task state machine / outbox，不允许空实现或直接改表

### 4.3 非目标

本里程碑不做：

- 新增大量 public-api 路径
- 完整 identity / RBAC
- annotation/import/export 迁移

## 5. 里程碑 B：Annotation 最小纵向闭环

### 5.1 目标

在 `public-api` 做实后，新增一条真正有业务价值的纵向链路：

- 创建 annotation
- 读取 annotation
- 对 FEDO 双视图样本调用本地 mapping sidecar
- 将映射结果落库并读回

### 5.2 范围

第一版只支持：

- `rect`
- `obb`
- create
- list

第一版不支持：

- update / delete
- draft / version chain
- 完整 label 工作流
- 大而全 annotation 管理能力

### 5.3 数据模型

建议新增最小表：

#### `sample`

- `id`
- `project_id`
- `dataset_type`
- `meta jsonb`
- `created_at`

#### `annotation`

- `id`
- `sample_id`
- `group_id`
- `label_id`
- `view`
- `annotation_type`
- `geometry jsonb`
- `attrs jsonb`
- `source`
- `is_generated`
- `created_at`

其中 `sample.meta jsonb` 第一阶段用于承载 lookup reference 等最小 metadata。  
这样 mapping sidecar 已经可以接入，而不必等待完整 artifact/import 系统迁完。

### 5.4 模块结构

建议新增或补齐：

```text
internal/modules/annotation/
├── domain/
├── app/
├── repo/
├── apihttp/
└── app/mapping/
```

职责如下：

- `domain/`：annotation 基本领域对象与 geometry 约束
- `app/`：create/list use case
- `repo/`：annotation 持久化与 sample metadata 读取
- `apihttp/`：public-api 适配层
- `app/mapping/`：已存在的 sidecar client，继续保持独立，不混入 repo 或 handler

### 5.5 API 边界

新增最小 API：

- `POST /samples/{sample_id}/annotations`
- `GET /samples/{sample_id}/annotations`

`POST` 的行为定义如下：

1. 接收 `rect/obb` annotation 请求。
2. 在 app 层完成 geometry normalize。
3. 从 repo 读取 `sample.meta`。
4. 写入用户提交的源 annotation。
5. 若 sample 满足 FEDO 双视图映射条件，则调用 mapping sidecar。
6. 将 sidecar 返回的目标视图 annotation 作为 generated annotation 一并写入。
7. 返回本次写入的 annotation 集合，而不是只返回单条源 annotation。

### 5.6 一致性选择

第一版 annotation 写路径采用强一致语义：

- sidecar 映射失败，则整次 annotation 创建失败
- 不做“先写源 annotation，映射失败再补偿”

原因：

1. 当前尚未引入 annotation outbox/workflow。
2. 本阶段目标是稳定最小闭环，而不是复杂异步流程。
3. 先定义部分成功语义会显著增加后续返工风险。

## 6. 数据流

### 6.1 现有 Public API

现有接口统一采用：

```text
handler -> app use case/query -> repo -> sqlc/pgx -> db
```

特别约束：

- 所有 runtime command 必须经过状态机
- public-api 不允许绕过状态机直接更新 `runtime_task`

### 6.2 Annotation Create

`POST /samples/{sample_id}/annotations` 的目标链路为：

```text
handler
  -> annotation app create use case
  -> repo 读取 sample metadata
  -> 写入 source annotation
  -> 调 mapping sidecar（按需）
  -> 写入 generated annotation
  -> 返回 annotation 列表
```

## 7. 测试策略

本阶段统一采用四层测试：

### 7.1 单元测试

覆盖：

- auth token 解析
- runtime state machine
- annotation geometry normalize
- mapping request/response 编解码

### 7.2 Repo 测试

覆盖：

- `project repo`
- `runtime repo`
- `annotation repo`

重点验证：

- SQL 映射
- 聚合查询
- 状态更新
- outbox 追加

### 7.3 API/HTTP 测试

覆盖：

- `project`
- `runtime-admin`
- `annotation`

重点验证：

- 请求/响应合同
- 鉴权
- 错误映射
- handler 到 use case 的接线

### 7.4 小型集成测试

至少保留两条：

1. `public-api` 启动后的真实 project/runtime-admin 路径
2. `annotation create` 调用本地 mapping sidecar 的真实链路

同时保留两类 mapping 测试：

- Go 侧 helper subprocess 测试，保证 controlplane framing/协议稳定
- Python 侧真实映射测试，保证 mapping engine 算法与 lookup 行为正确

## 8. 提交节奏

推荐拆成以下小提交：

1. `refactor(public-api): wire bootstrap dependencies`
2. `feat(project): back project api with repo store`
3. `feat(runtime): persist executor admin read model`
4. `feat(runtime): back runtime admin api with repos`
5. `feat(annotation): add annotation schema and repo`
6. `feat(annotation): add annotation create and list api`
7. `feat(annotation): wire FEDO mapping sidecar into create flow`

这样拆分的目的：

- 每步都可独立验证
- 每步都可独立 review
- 若中途调整设计，不会形成大面积返工

## 9. 明确暂缓项

以下内容明确不纳入本阶段：

- import/export 迁移
- 大面积扩充 public-api breadth
- 完整 annotation 生命周期管理
- 完整权限模型与资源级授权

## 10. 决策结论

本阶段不采用“先把 public-api 大部分接口都做出来”的路线。  
最终选择是：

1. 先把现有 public-api 做实，去掉 MemoryStore 与硬编码装配。
2. 再按纵向切片实现 annotation 最小闭环。
3. 在 `sample / annotation / mapping` 归宿稳定后，再进入 import/export 迁移。
