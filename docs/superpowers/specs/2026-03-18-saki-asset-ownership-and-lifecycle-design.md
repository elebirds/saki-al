# Saki Asset 归属与生命周期设计

日期：2026-03-18

## 1. 概述

本文档定义 `saki-controlplane` 中 asset 体系的长期数据模型，重点解决以下问题：

- asset 只作为对象存储元数据真相是否足够
- asset 与 `project / dataset / sample / runtime / import` 的归属关系如何表达
- import 过程文件与业务长期资产如何区分
- 删除 `dataset / project` 等业务对象时，物理对象何时删除
- 哪些宽松字符串应收缩成 enum

本设计的核心结论是：

1. `asset` 只表达物理对象真相，不直接表达业务归属。
2. 业务归属、过程归属、生命周期全部通过独立 `asset_reference` 层表达。
3. 删除业务对象时先删除引用，再通过异步 GC 回收无引用对象。
4. `import` 源包属于过程文件，不属于稳定业务资产。
5. `runtime artifact` 不会沉淀为 `dataset / sample` 资源；如需长期保留，只能新增 `project` 侧归属。
6. asset 相关核心字段尽量收缩为 enum，减少长期宽松字符串漂移。
7. 本文档只冻结数据模型、引用语义、最小接入路径与删除/GC 基础规则；owner-scoped API 迁移与细粒度权限收口属于后续独立 spec。

## 2. 现状约束

当前实现已经形成以下短期不能无视的约束：

1. `asset` 当前对外公开 `storage_backend / bucket / object_key`，这些字段已经成为公共 API 契约，短期不能直接移除。
2. `asset` 当前状态机只有 `pending_upload` 与 `ready` 两态，上传/下载 ticket 和完成上传都依赖这两个状态。
3. `asset` 当前与对象存储实现仍是单 provider、单 bucket、单 backend 的运行模型，实际运行值是 `minio`。
4. `importing` 仍维护独立的 `upload session + object_key` 过程真相层，尚未接入 `asset_id`。
5. `runtime ArtifactService` 当前直接按 `artifact_id == asset_id` 发放 ticket，runtime task 本身还没有 typed 的 asset 归属关系。

本设计必须兼容这些现实约束，但不把这些约束原样固化为长期模型。

## 3. 设计目标

本次设计应同时满足以下目标：

1. 让 `asset` 成为统一对象真相层，避免 importing、runtime、业务资产各自维护不同的对象身份模型。
2. 让业务归属从 `asset` 主表中解耦，以支持多引用、过程态与稳定态共存。
3. 让 `project / dataset / sample` 删除与对象物理删除解耦，避免误删或同步级联删除。
4. 为未来的对象 GC 提供统一判定基础。
5. 为权限模型提供可追踪的 owner 关系，而不是长期依赖全局 `asset_id`。
6. 通过 enum 收缩关键字段，避免字符串语义继续漂移。

## 4. 非目标

以下事项不属于本设计第一阶段：

1. 不在本轮直接收缩现有公共 API 中已公开的 `storage_backend / bucket / object_key` 字段。
2. 不在本轮实现完整多对象存储 backend 路由。
3. 不在本轮引入复杂版本化、审计保留或对象历史追踪。
4. 不在本轮把全部 importing 过程对象立即迁移到新的实现上。
5. 不在本轮设计跨项目共享资产的产品语义。
6. 不在本轮冻结 owner-scoped 公共 API 的最终路由形态。
7. 不在本轮完成细粒度权限收口的实施细节。

## 5. 核心建模决策

### 5.1 `asset` 只做物理对象真相

`asset` 表示对象存储中的一个物理对象，只回答以下问题：

- 这个对象是什么类型
- 它在存储中的位置是什么
- 它是否已完成上传
- 它的内容大小、内容类型、摘要和元数据是什么

`asset` 不回答以下问题：

- 这个对象属于哪个 `project / dataset / sample`
- 这个对象是否是某个业务对象的主资源
- 这个对象是否已经可以被 GC

### 5.2 归属使用 `asset_reference`

所有归属、角色、生命周期、可见性都放在 `asset_reference` 表中表达。

`asset_reference` 回答以下问题：

- 谁在引用这个 asset
- 这个引用是业务稳定态还是过程态
- 这个引用在该 owner 下扮演什么角色
- 该引用是否失效、是否过期

### 5.3 允许多引用，不要求单一所有者

一个 `asset` 可以被多个 owner 引用。

系统只允许定义“局部 primary reference”，不定义“全局唯一 owner”。也就是说：

- 同一个 `sample` 可以有一个主资源
- 同一个 `project` 可以有一个主附件角色的主资源
- 但同一个 `asset` 不要求全局上只能属于一个 owner

### 5.4 删除采用“删引用 + 异步 GC”

业务对象删除时，不同步删除物理对象。统一流程是：

1. 业务域删除或失效 owner
2. 相关 `asset_reference` 标记失效
3. GC 扫描无 active reference 的 asset
4. 由 GC 异步删除对象存储内容与 asset 记录

### 5.5 `import` 源包属于过程文件

导入原始 ZIP、JSON 包、预处理归档等对象属于过程文件。它们：

- 可以进入统一 `asset` 真相层
- 但只允许挂 `process` 生命周期引用
- 不属于稳定业务资产集合
- 默认在导入结束后由 TTL/GC 清理

### 5.6 `runtime artifact` 不进入 `dataset / sample`

`runtime artifact` 不会成为 `dataset / sample` 资产。

它的长期去向只有两种：

1. 保持为 `runtime_task` 过程态引用
2. 被业务侧采纳时，新增 `project` 侧 durable reference

它不会走 `runtime -> dataset -> sample` 的资产归属链。

## 6. 数据模型

### 6.1 `asset`

建议保留并收敛为以下结构：

```text
asset
- id uuid pk
- kind asset_kind
- status asset_status
- storage_backend asset_storage_backend
- bucket text
- object_key text
- content_type text
- size_bytes bigint
- sha256_hex text null
- metadata jsonb not null default '{}'
- created_by uuid null
- ready_at timestamptz null
- orphaned_at timestamptz null
- created_at timestamptz
- updated_at timestamptz
- unique(storage_backend, bucket, object_key)
```

约束：

1. `asset` 不直接保存 `project_id / dataset_id / sample_id / runtime_task_id`。
2. `kind`、`status`、`storage_backend` 使用 enum 或等价强类型。
3. 唯一对象身份由 `(storage_backend, bucket, object_key)` 表达。
4. `ready_at` 记录 asset 首次进入 `ready` 的时间。
5. `orphaned_at` 记录 asset 失去最后一个 active reference 的时间；只要存在 active reference，则必须为 `null`。
6. 对一个已 orphan 的 asset 新增 active reference 时，必须在同一事务内将 `orphaned_at` 清空。

### 6.2 `asset_reference`

建议新增：

```text
asset_reference
- id uuid pk
- asset_id uuid not null references asset(id)
- owner_type asset_owner_type not null
- owner_id uuid not null
- role asset_reference_role not null
- lifecycle asset_reference_lifecycle not null
- is_primary boolean not null default false
- metadata jsonb not null default '{}'
- created_by uuid null
- created_at timestamptz
- expires_at timestamptz null
- deleted_at timestamptz null
```

语义：

1. `owner_type + owner_id` 表示引用宿主。
2. `role` 表示该 asset 在宿主中的业务角色。
3. `lifecycle` 表示该引用是过程态还是稳定态。
4. `deleted_at` 非空表示引用失效，不再参与权限和 GC 存活判断。
5. `expires_at` 主要用于过程态引用的 TTL。
6. 系统不允许“无 owner 引用”；所有 `asset_reference` 必须明确指向一个 owner。

### 6.3 必要索引与约束

建议新增以下约束：

```text
index on asset_reference(owner_type, owner_id) where deleted_at is null
index on asset_reference(asset_id) where deleted_at is null
unique(asset_id, owner_type, owner_id, role) where deleted_at is null
unique(owner_type, owner_id, role) where is_primary = true and deleted_at is null
```

解释：

1. 同一个 owner 下同一 role 不应重复引用同一个 asset。
2. 同一个 owner 下同一 role 最多一个 `is_primary=true`。
3. 已删除引用不参与唯一性判断。

### 6.4 判定规则

为避免权限、查询、GC 各自发明不同判定逻辑，统一冻结以下谓词：

```text
active_reference(now) :=
  deleted_at is null
  and (expires_at is null or expires_at > now)

expired_reference(now) :=
  deleted_at is null
  and expires_at is not null
  and expires_at <= now

gc_candidate_ready(now) :=
  asset.status = ready
  and no active_reference(now)
  and asset.orphaned_at is not null
  and asset.orphaned_at <= now - retention_window

gc_candidate_stale_pending(now) :=
  asset.status = pending_upload
  and no active_reference(now)
  and asset.created_at <= now - upload_grace_window
```

补充规则：

1. `active_reference` 是 owner-scoped 查询、权限判断、GC 存活判定的统一谓词。
2. `expired_reference` 在逻辑上已不活跃，即使后台任务尚未把它写成 `deleted_at`。
3. `retention_window` 用于 `ready` 对象的最小保留期。
4. `upload_grace_window` 用于清理长期未完成上传的 `pending_upload` 对象。
5. 由于数据库唯一约束只直接识别 `deleted_at is null`，任何可能创建冲突引用的写路径都必须先在同一事务内物化本范围内的 expired reference，将其写成 `deleted_at=now()`。

### 6.5 核心用例边界

为保证 polymorphic owner 校验和事务边界可规划，冻结以下职责分配：

1. `asset` 模块负责：
   - `asset.kind / status / storage_backend` 校验
   - `owner_type x role x lifecycle x is_primary` 合法组合校验
   - primary 唯一性与重复引用约束
   - `ready_at / orphaned_at` 维护
   - expired reference 物化
2. owner 存在性校验通过 `OwnerResolver` 一类的 owner-aware 适配接口完成；`asset` 模块不直接 import `project / dataset / sample / runtime / import` repo。
3. 从 asset 侧发起的核心用例包括：
   - `CreateProcessReference`
   - `CreateDurableReference`
   - `AdoptRuntimeArtifact`
   它们由 asset 应用层开启或接收事务，并在事务内调用 owner 适配器校验 owner 存在。
4. 从 owner 侧发起的删除用例中，owner 模块负责开启事务，并在同一事务内调用 `InvalidateReferencesForOwner(owner_type, owner_id)`。
5. 当前 scope 内所有 owner 真相都位于同一数据库，因此 owner 删除与引用失效不允许跨事务完成。

## 7. 枚举设计

### 7.1 `asset_kind`

表示对象本体类别，建议收缩为：

- `image`
- `video`
- `archive`
- `document`
- `binary`

约束：

- `kind` 不承载流程语义
- `kind` 不承载业务归属语义
- 更精确格式继续看 `content_type`

### 7.2 `asset_status`

短期保持：

- `pending_upload`
- `ready`

本轮不引入 `deleted`、`expired`、`gc_pending` 等状态，避免把 GC 语义混入主状态机。

### 7.3 `asset_storage_backend`

短期枚举值只有：

- `minio`

即使运行时当前只有一个 backend，也应收敛为 enum，而不是继续使用宽松字符串。

### 7.4 `asset_owner_type`

建议收缩为：

- `project`
- `dataset`
- `sample`
- `runtime_task`
- `import_upload_session`
- `import_task`

### 7.5 `asset_reference_role`

建议第一阶段只保留：

- `primary`
- `attachment`
- `source_package`
- `artifact`
- `preview`

不提前引入 `thumbnail`、`mask`、`embedding`、`report`、`export_bundle` 等未稳定角色。

### 7.6 `asset_reference_lifecycle`

建议收缩为：

- `process`
- `durable`

### 7.7 不收缩为 enum 的字段

以下字段保持开放字符串或 JSON：

- `content_type`
- `object_key`
- `metadata`

原因是这些字段天然由外部格式、存储布局和产品附加信息驱动，不适合过早固化。

## 8. 归属合法组合矩阵

第一阶段冻结以下合法组合：

| owner_type | role | lifecycle | is_primary |
|---|---|---|---|
| `project` | `attachment` | `durable` | 可为 `true` |
| `dataset` | `attachment` | `durable` | 可为 `true` |
| `sample` | `primary` | `durable` | 必须为 `true` |
| `sample` | `attachment` | `durable` | 必须为 `false` |
| `runtime_task` | `artifact` | `process` | 必须为 `false` |
| `import_upload_session` | `source_package` | `process` | 必须为 `false` |
| `import_task` | `source_package` | `process` | 必须为 `false` |

额外约束：

1. `sample + primary + durable` 表示样本主资源，同一 sample 最多一条 active primary。
2. `runtime_task` 当前只允许挂 `artifact`，不允许 durable 引用。
3. `import` 当前只允许 `source_package` 过程引用。
4. `preview` 作为 enum 预留值，仅用于未来“导入派生预览对象”场景，不属于本文档当前实施范围，也不出现在本轮合法组合矩阵中。

## 9. 归属与角色语义

### 9.1 `project`

`project` 可引用长期保留的项目级资产。

推荐语义：

- `owner_type=project`
- `role=attachment`
- `lifecycle=durable`

如果某个 `runtime artifact` 被业务采纳，不迁移 asset，只新增 `project` 侧 durable reference。

### 9.2 `dataset`

`dataset` 只引用属于数据集层面的稳定资产，不承接 runtime 产物。

推荐语义：

- `owner_type=dataset`
- `role=attachment`
- `lifecycle=durable`

### 9.3 `sample`

`sample` 主要承接样本主资源与样本附属资源。

推荐语义：

- 主资源：`owner_type=sample`，`role=primary`，`lifecycle=durable`
- 附属资源：`owner_type=sample`，`role=attachment`，`lifecycle=durable`

### 9.4 `runtime_task`

runtime task 产物默认属于过程态引用。

推荐语义：

- `owner_type=runtime_task`
- `role=artifact`
- `lifecycle=process`

当该产物被业务决定长期保留时，只新增 `project` durable reference；是否保留原 `runtime_task` 引用，由保留期策略决定。

### 9.5 `import_upload_session`

导入原始包、原始 ZIP、导入源文档挂在 upload session 下。

推荐语义：

- `owner_type=import_upload_session`
- `role=source_package`
- `lifecycle=process`

它不是稳定业务资产。

### 9.6 `import_task`

如执行阶段仍需持有导入源包，可新增第二条过程引用：

- `owner_type=import_task`
- `role=source_package`
- `lifecycle=process`

这允许 upload session 完成后，导入任务继续持有原始导入包，直到任务结束或超时。

`preview` 仅保留为 future enum，用于未来真正落对象存储的派生预览结果，不用于表示原始导入包。

## 10. 创建流程

### 10.1 稳定业务资产上传

流程：

1. 创建 `asset(status=pending_upload)`
2. 不创建 durable `asset_reference`
3. 上传前的 owner 关系只表现为一次 owner-scoped upload intent；该 intent 不属于 `asset_reference` 真相层
4. 发放上传 ticket
5. 上传完成后，在同一事务内：
   - 将 `asset` 标记为 `ready`
   - 写入 `ready_at`
   - 创建 durable `asset_reference`
   - 保持 `orphaned_at = null`

失败策略：

1. durable 业务引用只在上传完成后创建，因此“签名后放弃上传”不会遗留 active durable reference。
2. 显式取消 pending durable upload 时，不做同步硬删；只失效 upload intent，让该 pending asset 继续保持“无 active reference”状态。
3. 未完成上传的 pending durable asset 统一由 `upload_grace_window` 驱动的 stale pending GC 收口。

### 10.2 runtime artifact

流程：

1. 创建 `asset(status=pending_upload, kind=...)`
2. 创建 `runtime_task + artifact + process` 引用，并写入 `expires_at`
3. 通过内部 RPC 发放上传 ticket
4. 上传完成后 asset 进入 `ready`，写入 `ready_at`
5. 如被业务采纳，新增 `project + attachment + durable` 引用

### 10.3 import 源包

流程：

1. 创建 `asset(status=pending_upload, kind=archive)`
2. 创建 `import_upload_session + source_package + process` 引用，并写入 `expires_at`
3. 上传完成后 asset 进入 `ready`，写入 `ready_at`
4. `prepare / execute` 阶段使用该对象
5. upload session 完成后，如导入任务需要继续持有对象，则新增 `import_task + source_package + process` 引用，并写入 `expires_at`
6. 任务结束后过程引用过期

## 11. 删除与 GC

### 11.1 删除业务对象

删除 `project / dataset / sample` 时：

1. owner 真相删除与相关 `asset_reference.deleted_at` 更新必须在同一数据库事务内完成
2. 同一事务内若最后一个 active reference 被失效，asset 模块必须把对应 `asset.orphaned_at` 写为当前时间
3. 若引用失效写入失败，则 owner 删除事务整体回滚
4. 不直接删除对象存储内容

对于历史遗留或异常形成的 dangling reference，允许后台 repair job 按 owner 缺失关系补写 `deleted_at`，但这只是补偿路径，不是主路径。

### 11.2 过程态过期

对于 `import_upload_session / import_task / runtime_task` 的过程引用：

1. 可配置 `expires_at`
2. 到期后由后台 job 将其物化为 `deleted_at=now()`
3. 若该失效导致 asset 丢失最后一个 active reference，则同步写入 `asset.orphaned_at=now()`
4. 失效后不再视为 active reference

### 11.3 GC 候选条件

一个 asset 成为 GC 候选，需同时满足：

1. 满足 `gc_candidate_ready(now)` 或 `gc_candidate_stale_pending(now)`
2. 不存在任何 active reference
3. 满足相应保留窗口

其中：

- `ready` 对象按 `retention_window` 判定
- `pending_upload` 对象按 `upload_grace_window` 判定
- `ready` 对象的保留期从 `orphaned_at` 开始计算，而不是从 `updated_at` 计算

### 11.4 GC 动作

GC 执行步骤：

1. 对 `ready` 对象，删除对象存储里的物理对象，然后删除 `asset` 行
2. 对 stale `pending_upload` 对象，最佳努力删除对象存储里的残留对象，然后删除 `asset` 行
3. 如需要审计，再额外设计 tombstone 或审计表

本轮不把“已删除”编码进 `asset.status`。

### 11.5 删除语义选择

本设计明确采用：

- 业务删除先删引用
- 物理删除交给异步 GC

不采用同步硬删。

## 12. 最小权限语义

本 spec 只冻结最小权限语义，不定义最终 owner-scoped 公共 API 路由。

### 12.1 统一规则

对未来所有会暴露对象内容、下载票据、上传票据的接口，统一采用：

1. 调用方必须提供明确 owner 上下文
2. 授权成功条件为：
   - 调用方对该 owner 有相应权限
   - 存在一条从该 owner 指向该 asset 的 active reference

也就是说，多引用 asset 的授权规则不是“任一 owner 都可隐式放行”，而是“必须在明确 owner 上下文下判定”。

唯一例外是 durable 上传的预完成阶段：

1. 上传 ticket 可以在“无 active durable reference”前提下发放
2. 其授权依据不是 `asset_reference`，而是 owner-scoped upload intent
3. 完成上传时必须再次在同一事务内校验 owner 上下文，并创建 durable `asset_reference`

### 12.2 临时兼容

在 `project / dataset / sample` 的 owner-scoped API 完整落地前：

1. 现有 public asset API 仍可继续存在
2. 但至少应做粗粒度 `assets:read / assets:write`
3. 不应把全局 `asset_id` 当成长期稳定授权边界

### 12.3 runtime

`runtime ArtifactService` 应视为内部 RPC。长期目标是：

1. 只供受信 runtime 角色调用
2. 不作为对外裸 ticket 发放入口
3. 其权限语义由 `runtime_task` 对 asset 的引用关系支撑

## 13. 过渡桥与兼容边界

### 13.1 短期兼容

短期保留当前公共 API 返回的：

- `storage_backend`
- `bucket`
- `object_key`

原因是这些字段已经成为外部契约。

### 13.2 过渡桥

长期桥接签名应为：

`GetByStorageLocation(storage_backend, bucket, object_key)`

当前仓库中不带 `storage_backend` 的辅助接口只代表单 backend 现实，不应外溢为长期契约。

## 14. 本 spec 的实施范围

本文档冻结的计划范围仅包括：

1. `asset` 与 `asset_reference` 数据模型
2. enum 收敛
3. 稳定业务资产、runtime artifact、import 源包的最小接入语义
4. 删除与 GC 的基础规则

以下内容明确不属于本 spec 的单次实施计划：

1. owner-scoped 公共 API 全量迁移
2. 细粒度权限系统收口
3. 多 backend provider registry
4. 完整审计与 tombstone 设计

## 15. 分阶段实施计划

### Phase 1：基础模型收敛

1. 将 `asset.kind / status / storage_backend` 收敛为 enum
2. 将 `asset` 唯一键收紧为 `(storage_backend, bucket, object_key)`
3. 新增 `asset_reference` 表与基础 repo/usecase
4. provider 增加删除对象能力，为 GC 做准备

### Phase 2：durable 业务资产接入

1. 新的业务资产创建流程统一创建 `pending asset`
2. 在 complete/finalize 时原子创建 durable `asset_reference`
3. 先服务 `project / dataset / sample`
4. 内部实现改为 reference-aware

### Phase 3：runtime 接入

1. runtime task 产物创建时同步创建 `process reference`
2. 项目采纳 runtime 产物时，只新增 `project` durable reference
3. 明确禁止 runtime 产物直接变成 `dataset / sample` 资产

### Phase 4：import 接入

1. import upload session 创建时同步创建 `asset + process reference`
2. `upload_session` 真相逐步从 `object_key` 过渡到 `asset_id`
3. `prepare / execute` 通过 asset 读取对象
4. 导入结束后过程引用按 TTL 过期

### Phase 5：GC 上线

1. 扫描孤儿 asset
2. 删除对象存储内容
3. 删除 `asset` 行
4. 增加重试、幂等和保留期控制

本轮计划到此结束。权限与 API 收口另起后续 spec。

## 16. 最终决策摘要

本设计最终冻结以下决策：

1. `asset` 是物理对象真相，不直接承载归属。
2. 所有归属与生命周期都通过 `asset_reference` 表达。
3. 一个 asset 允许多引用，不要求全局唯一 owner。
4. `import` 源包是过程文件，不是稳定业务资产。
5. `runtime artifact` 不进入 `dataset / sample` 归属链。
6. 删除采用“删引用 + 异步 GC”。
7. `kind / status / storage_backend / owner_type / role / lifecycle` 全部收敛为 enum。

这套模型既能兼容当前实现约束，也能为后续 `dataset / project / sample` 归属、runtime 过程产物、过程文件清理和统一 GC 提供稳定基础。
