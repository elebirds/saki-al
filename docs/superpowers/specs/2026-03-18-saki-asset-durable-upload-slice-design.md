# Saki Asset Durable Upload Slice 设计

日期：2026-03-18

## 1. 概述

本文档是 [2026-03-18-saki-asset-ownership-and-lifecycle-design.md](/Users/hhm/code/saki/docs/superpowers/specs/2026-03-18-saki-asset-ownership-and-lifecycle-design.md) 的当前实施切片。

本文只冻结一个可直接进入 implementation planning 的 work package：

- `asset` 基础模型收敛
- `asset_reference` durable 归属层
- durable 业务资产上传路径
- `upload intent` 最小契约

本文明确不覆盖：

- runtime artifact 接入
- import 过程文件接入
- 完整 GC 上线
- owner-scoped 公共 API 全量迁移
- 细粒度权限收口

## 2. 目标

本切片应完成以下目标：

1. 把 `asset.kind / status / storage_backend` 收敛为 enum。
2. 为 `asset` 增加 GC 所需的明确时间锚点。
3. 新增 `asset_reference`，用于 durable 业务归属。
4. 冻结 durable 上传路径，使其在上传前不创建 durable reference，但具备稳定的授权、取消、完成和幂等语义。
5. 让 `project / dataset / sample` 三类 owner 可以在上传完成后原子绑定到 asset。

## 3. 范围

### 3.1 In Scope

1. `asset` 表结构修改
2. `asset_reference` 表新增
3. `asset_upload_intent` 表新增
4. durable 上传 init / complete / cancel 语义
5. `project / dataset / sample` owner 适配边界
6. 最小 stale pending 清理规则

### 3.2 Out of Scope

1. `runtime_task` / `import_upload_session` / `import_task` 引用落地
2. durable asset 下载授权的 owner-scoped API 设计
3. 统一孤儿 GC 扫描器的完整实现
4. 多 backend provider registry
5. tombstone / 审计保留

## 4. 数据模型

### 4.1 `asset`

本切片冻结以下字段：

```text
asset
- id uuid pk
- kind asset_kind not null
- status asset_status not null
- storage_backend asset_storage_backend not null
- bucket text not null
- object_key text not null
- content_type text not null
- size_bytes bigint not null default 0
- sha256_hex text null
- metadata jsonb not null default '{}'
- created_by uuid null
- ready_at timestamptz null
- orphaned_at timestamptz null
- created_at timestamptz not null
- updated_at timestamptz not null
- unique(storage_backend, bucket, object_key)
```

约束：

1. `ready_at` 在 `pending_upload -> ready` 时写入，之后不再回写。
2. `orphaned_at` 仅用于 `ready` asset；有 active durable reference 时必须为 `null`。
3. 当前切片内，`orphaned_at` 只由 durable reference 的增删维护。
4. init 时必须写入 `kind / storage_backend / bucket / object_key / content_type / metadata / created_by`；此时 `size_bytes=0`、`sha256_hex=null`、`ready_at=null`、`orphaned_at=null`。
5. complete 时只允许更新 `status / size_bytes / sha256_hex / content_type / ready_at / updated_at`；`kind / storage_backend / bucket / object_key / metadata / created_by` 在 init 后不可变。

### 4.2 `asset_reference`

本切片只支持 durable 业务引用：

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
- created_at timestamptz not null
- deleted_at timestamptz null
```

本切片内固定：

- `lifecycle = durable`
- 不使用 `expires_at`

唯一约束：

```text
non-unique index on asset_reference(owner_type, owner_id) where deleted_at is null
non-unique index on asset_reference(asset_id) where deleted_at is null
unique(asset_id, owner_type, owner_id, role) where deleted_at is null
unique(owner_type, owner_id, role) where is_primary = true and deleted_at is null
```

### 4.3 `asset_upload_intent`

为解决“durable 上传前无 reference，但仍需授权与幂等”的问题，本切片新增显式 intent 层：

```text
asset_upload_intent
- id uuid pk
- asset_id uuid not null unique references asset(id) on delete cascade
- owner_type asset_owner_type not null
- owner_id uuid not null
- role asset_reference_role not null
- is_primary boolean not null default false
- declared_content_type text not null
- state asset_upload_intent_state not null
- idempotency_key text not null
- expires_at timestamptz not null
- created_by uuid null
- completed_at timestamptz null
- canceled_at timestamptz null
- created_at timestamptz not null
- updated_at timestamptz not null
```

枚举：

```text
asset_upload_intent_state
- initiated
- completed
- canceled
- expired
```

约束：

1. 一个 pending durable asset 在任一时刻最多一个 upload intent。
2. `asset_upload_intent` 是上传前 owner 关系的唯一真相。
3. durable `asset_reference` 只在 complete/finalize 成功时创建。
4. `asset_upload_intent` 与 `asset` 的删除关系由 `asset_id -> asset(id) on delete cascade` 表达；stale pending 清理删除 `asset` 时，关联 intent 必须同步删除，不保留游离 intent。
5. `idempotency_key` 的唯一作用域是 `(owner_type, owner_id, role, idempotency_key)`。
6. 相同 idempotency key 代表同一个 init 请求；若重试请求的不可变字段不一致，必须返回 idempotency conflict。
7. `declared_content_type` 持久化 init 时的声明值，只用于幂等比较与 finalize 兜底；它不要求等于最终对象探测出的 `asset.content_type`。

## 5. 枚举冻结

### 5.1 `asset_kind`

- `image`
- `video`
- `archive`
- `document`
- `binary`

### 5.2 `asset_status`

- `pending_upload`
- `ready`

### 5.3 `asset_storage_backend`

- `minio`

### 5.4 `asset_owner_type`

本切片只允许：

- `project`
- `dataset`
- `sample`

### 5.5 `asset_reference_role`

本切片只允许：

- `attachment`
- `primary`

### 5.6 `asset_reference_lifecycle`

本切片只允许：

- `durable`

## 6. 合法组合

本切片只冻结以下组合：

| owner_type | role | is_primary |
|---|---|---|
| `project` | `attachment` | 可为 `true` |
| `dataset` | `attachment` | 可为 `true` |
| `sample` | `primary` | 必须为 `true` |
| `sample` | `attachment` | 必须为 `false` |

约束：

1. `sample + primary` 表示样本主资源，同一 sample 最多一个 active primary。
2. `project` 和 `dataset` 当前只支持 `attachment`。
3. 任何不在上表中的 owner/role/is_primary 组合都应被拒绝。
4. 本切片不在 init 阶段预占 `is_primary=true` 的唯一槽位，也不为一般 durable reference 建 reservation。
5. 与 active durable reference 的唯一性冲突统一在 complete 事务内收口；若命中冲突，complete 必须失败，intent 保持原状，后续由调用方 cancel 或等待 expire。

## 7. 判定规则

本切片冻结以下统一谓词：

```text
active_durable_reference :=
  deleted_at is null

live_upload_intent(now) :=
  state = initiated
  and expires_at > now

stale_pending_asset(now) :=
  asset.status = pending_upload
  and not exists live_upload_intent(now)
  and not exists active_durable_reference
  and asset.created_at <= now - upload_grace_window
```

补充规则：

1. 在本切片内，durable reference 没有 `expires_at` 语义。
2. `pending_upload` asset 的清理锚点是 `created_at`，不是 `updated_at`。
3. `ready` asset 的 orphan 判断锚点是 `orphaned_at`，但完整 ready-GC 不属于本切片实现范围。
4. `upload_grace_window` 是 pending asset 的最终保留上限，始终从 `asset.created_at` 开始计算。
5. `asset_upload_intent.expires_at` 必须满足 `asset.created_at < expires_at <= asset.created_at + upload_grace_window`。
6. `canceled_at` 和 `expired` 只负责让 intent 失活，不会重置 pending asset 的保留时钟；一旦 intent 不再 live，asset 是否可删只由 `asset.created_at + upload_grace_window` 判定。

## 8. Upload Intent 契约

### 8.1 绑定字段

一个 intent 必须绑定以下信息：

- `asset_id`
- `owner_type`
- `owner_id`
- `role`
- `is_primary`
- `declared_content_type`
- `created_by`
- `idempotency_key`
- `expires_at`

这些字段在 init 后不可变。

同一次 durable 上传的“不可变 init 合同”还包括 `asset.kind / asset.metadata / intent.declared_content_type`。也就是说：

1. intent 负责绑定 owner、role、幂等键与过期时间。
2. `intent.declared_content_type` 负责保存 init 时声明的内容类型，用于幂等比较。
3. `asset` 负责绑定该次上传的物理落点与对象声明值。
4. `asset.content_type` 在 init 时先写入声明值，但 complete 后可以被 provider 探测结果覆盖；因此它不是重复 init 判定的唯一依据。
5. `asset.kind / asset.metadata` 在 init 后保持不可变。
6. 对同一 `(owner_type, owner_id, role, idempotency_key)` 的重试，若上述不可变字段任一不一致，必须返回 idempotency conflict，而不是复用既有 intent。

### 8.2 存续介质

`upload intent` 必须持久化到数据库，不允许只存在于内存或客户端状态中。

原因：

1. 需要支撑 complete 的幂等与重试
2. 需要支撑 cancel
3. 需要支撑过期清理
4. 需要支撑无 reference 场景下的授权判定

### 8.3 Init 语义

durable 上传初始化时，在同一事务内执行：

1. 校验 owner 存在
2. 校验 owner/role/is_primary 组合合法
3. 按 `(owner_type, owner_id, role, idempotency_key)` 查询既有 intent
4. 若不存在既有 intent，则创建 `asset(status=pending_upload)`，并写入：
   - `kind`
   - `storage_backend`
   - `bucket`
   - `object_key`
   - `content_type`
   - `metadata`
   - `created_by`
   - 若命中 `unique(storage_backend, bucket, object_key)`，视为服务端生成的 object location 冲突；实现必须在同一 init 请求内重新生成 `object_key` 并重试，直到成功或达到内部重试上限
5. 若不存在既有 intent，则创建 `asset_upload_intent(state=initiated)`，并写入 `declared_content_type`
6. 若已存在 intent，必须比对不可变 init 合同：
   - `owner_type / owner_id / role / is_primary`
   - `created_by`
   - `asset.kind / asset.metadata`
   - `intent.declared_content_type`
7. 对已存在且合同一致的 intent：
   - 若 `state=initiated` 且未过期，返回既有 `asset_id`，并对同一 `object_key` 重新签发 upload ticket
   - 若 `state=initiated` 但 `expires_at <= now`，应先将 intent 视为已过期；实现可以在同一事务内把它改写为 `expired`，随后返回冲突，要求调用方使用新的 `idempotency_key`
   - 若 `state=completed`，返回既有 `asset_id` 与最终状态，不再新建 asset/intent
   - 若 `state=canceled` 或 `state=expired`，返回冲突，要求调用方使用新的 `idempotency_key`
8. 返回 `asset_id` 与上传结果；仅在 `state=initiated` 路径返回 upload ticket

此阶段不创建 durable reference。

补充规则：

1. init 不检查 active durable reference 的最终唯一性冲突。
2. init 不为 `sample + primary` 预留唯一槽位。
3. `object_key` 由服务端生成，complete 请求不重新提交 `bucket / object_key`。
4. `(storage_backend, bucket, object_key)` 冲突不属于业务冲突，也不属于 idempotency conflict；若内部重试仍失败，应返回系统错误。

### 8.4 Complete 语义

complete/finalize 时，在同一事务内执行：

1. 按 `asset_id` 加载 intent 与 asset
2. 若 `intent.state=completed`，走幂等重放分支：
   - 校验 `asset.status=ready`
   - 校验 durable `asset_reference` 已存在，且其 `owner_type / owner_id / role / is_primary` 与 intent 一致
   - 若一致，直接返回最终状态
   - 若不一致，视为不一致状态，返回错误并交给人工/修复任务处理
3. 若 `intent.state` 不是 `initiated` 或 `completed`，拒绝 complete
4. 对 `state=initiated` 的正常路径，校验 intent 未过期、未取消
   - 若 `expires_at <= now`，必须拒绝 complete；实现可以在同一事务内先把 intent 改写为 `expired`
5. 校验远端对象存在，校验位置为 asset 上已冻结的 `(storage_backend, bucket, object_key)`
6. complete 请求与远端对象的匹配规则固定为：
   - 若请求携带 `size_bytes`，必须等于 provider `StatObject` 得到的大小
   - `sha256_hex` 若由调用方提供，只写入 `asset.sha256_hex`，本切片不要求对象存储侧摘要校验
   - `content_type` 以 provider `StatObject` 返回值优先；若 provider 未返回，则回退到 `intent.declared_content_type`
   - `metadata` 不参与 complete 匹配，也不在 complete 阶段修改
7. 再次校验 owner 存在
8. 校验 durable reference 唯一性冲突：
   - 不允许与既有 active durable reference 违反 `(asset_id, owner_type, owner_id, role)` 唯一约束
   - 不允许与既有 `is_primary=true` active durable reference 违反 `(owner_type, owner_id, role)` 唯一约束
9. 将 `asset.status` 置为 `ready`
10. 将 `asset.size_bytes` 写为 provider `StatObject` 的最终大小
11. 将 `asset.sha256_hex` 写为请求提供值或保持 `null`
12. 将 `asset.content_type` 写为上文解析出的最终 `content_type`
13. 写入 `ready_at`
14. 创建 durable `asset_reference`
15. 将 intent 标记为 `completed`
16. 保持 `orphaned_at = null`

幂等要求：

1. 同一 `asset_id` 的重复 complete，若 intent 已 `completed` 且 durable reference 已落库，应返回成功并重放最终状态。
2. 若 `intent.state=completed`，但 `asset.status!=ready` 或 durable reference 缺失/不匹配，视为不一致，返回错误并交给人工/修复任务处理，不做静默修补。
3. 若 `state=initiated` 但 complete 时命中 durable reference 唯一约束冲突，应返回冲突；此时 asset 维持 `pending_upload`，intent 保持 `initiated`，由调用方后续 cancel 或等待 expire。

### 8.5 Cancel 语义

cancel 时，在同一事务内执行：

1. 按 `asset_id` 加载 intent
2. 若 `state=initiated`，将其标记为 `canceled`
3. 不创建 durable reference
4. 不同步删除 asset
5. 后续由 stale pending 清理收口

幂等要求：

1. 重复 cancel 返回当前 intent 状态
2. 对已 `completed` 的 intent，不允许 cancel

### 8.6 Expire 语义

后台任务定期执行：

1. 查找 `state=initiated and expires_at <= now`
2. 将 intent 标记为 `expired`
3. 不同步删除 asset
4. 让对应 pending asset 在达到 `asset.created_at + upload_grace_window` 后进入 stale pending 清理路径

## 9. 事务边界与职责

### 9.1 `asset` 模块职责

`asset` 模块负责：

1. `asset`、`asset_reference`、`asset_upload_intent` 的持久化
2. owner/role/is_primary 合法组合校验
3. `ready_at / orphaned_at` 维护
4. complete/cancel/expire 的状态机约束

### 9.2 owner 存在性校验

owner 存在性通过 `OwnerResolver` 一类适配接口完成。

约束：

1. `asset` 模块不直接 import `project / dataset / sample` repo
2. owner 存在性校验必须在同一事务快照下完成

### 9.3 事务归属

1. `InitDurableUpload`
2. `CompleteDurableUpload`
3. `CancelDurableUpload`

以上三个用例均由 asset 应用层拥有主事务。

### 9.4 owner 删除

owner 删除与 durable reference 失效不属于本切片实现，但接口前提先冻结：

1. owner 删除方必须在同一数据库事务内调用 `InvalidateReferencesForOwner`
2. 若最后一个 active durable reference 被删，asset 模块负责写入 `orphaned_at`

## 10. 最小 API/授权语义

本切片不设计最终 owner-scoped 公共 API 路由，只冻结最小授权规则。

### 10.1 上传 ticket

durable 上传 ticket 的授权依据是：

1. 调用方对该 owner 有写权限
2. 存在一条 live upload intent
3. 该 intent 的 owner 绑定与请求 owner 上下文一致

上传前不要求已有 durable reference。

### 10.2 完成上传

complete 的授权依据是：

1. 调用方对该 owner 有写权限
2. intent 处于 `initiated`，或处于 `completed` 且本次请求只是在重放最终状态
3. intent 中绑定的 `owner_type / owner_id / role / is_primary` 与 finalize 路径一致

### 10.3 读取与下载

读取与下载不属于本切片实现范围。后续实现时，应基于 active durable reference 做 owner-scoped 授权。

## 11. 清理规则

本切片只冻结 stale pending 清理，不实现完整 ready GC。

后台清理器规则：

1. 扫描 `stale_pending_asset(now)`
2. 最佳努力删除对象存储残留对象
3. 删除 `asset`
4. 依赖 `asset_upload_intent.asset_id -> asset(id) on delete cascade` 同步删除关联 intent；清理器不保留 stale pending asset 的终态 intent

## 12. 测试要求

本切片实现至少应覆盖：

1. `InitDurableUpload` 创建 pending asset 与 intent
2. 非法 owner/role/is_primary 组合被拒绝
3. 相同 `(owner_type, owner_id, role, idempotency_key)` 的重复 init：
   - 在 `initiated` 状态下重放同一 `asset_id`
   - 在字段不一致时返回 idempotency conflict
4. `CompleteDurableUpload` 原子创建 durable reference
5. 重复 complete 在 `completed` 状态下重放最终状态
6. 对 `canceled / expired` intent 的 complete 被拒绝
7. 对 `state=initiated` 但 `expires_at <= now` 的 intent，init/complete 都按过期路径处理
8. `CancelDurableUpload` 不创建 reference，且不硬删 asset
9. 对已 `completed` 的 intent，cancel 被拒绝
10. 过期 intent 使 pending asset 进入 stale pending 清理，并在删除 asset 时级联删除 intent
11. `sample + primary` 的唯一约束，以及 complete 时的冲突失败行为
12. `upload_grace_window` 始终从 `asset.created_at` 计算；`expired/canceled` 只让 intent 失活，不重置清理时钟
13. init 命中 `(storage_backend, bucket, object_key)` 冲突时会重试生成新的 `object_key`，且不会误报为业务冲突
14. finalize 会把 provider 探测出的 `size_bytes` 持久化到 `asset.size_bytes`
15. 新增/删除 durable reference 时 `orphaned_at` 的维护

## 13. 实施顺序

1. 迁移 `asset` 表，新增 enum、`ready_at`、`orphaned_at`
2. 新增 `asset_reference`
3. 新增 `asset_upload_intent`
4. 实现 asset 应用层的 init/complete/cancel 用例
5. 接上现有 durable 业务资产上传入口
6. 补齐 stale pending 清理器
7. 补齐测试

## 14. 验收标准

本切片完成时，应满足：

1. durable 上传前不创建 durable reference
2. durable complete 后一定创建 durable reference
3. cancel 不做同步硬删
4. stale pending 能被统一收口
5. owner/role/is_primary 非法组合无法落库
6. 该切片不依赖 runtime/import/完整 GC 才能成立
