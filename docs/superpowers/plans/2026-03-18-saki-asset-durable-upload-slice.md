# Saki Asset Durable Upload Slice Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `saki-controlplane` 的 asset 与对象存储基础上，落地 durable asset 上传切片：新增 `asset_reference` 与 `asset_upload_intent`，把 `project / dataset / sample` 的 durable 归属、init/complete/cancel 幂等语义、以及最小 stale pending 清理跑通。

**Architecture:** 继续保留 `asset` 作为物理对象真相层，在数据库中补齐 enum、`ready_at`、`orphaned_at`、`asset_reference`、`asset_upload_intent`；应用层新增 transaction-owned durable upload usecase，owner 存在性通过独立 adapter 解析，不把 `asset` 模块绑死到其他 repo。公共 API 先沿用当前 `/assets/...` 入口，只扩充 owner 绑定、幂等键和 cancel 语义，不在本轮做最终 owner-scoped 路由迁移。

**Tech Stack:** Go, PostgreSQL, goose, sqlc, ogen, pgx/v5, MinIO, testcontainers-go

---

**Execution Note:** 当前 workspace 仍有一处与本计划无关的未提交改动：[runtime_task_lifecycle_test.go](/Users/hhm/code/saki/saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go)。执行本计划时不要把它混入 asset 切片提交。

## Planned Files

- Modify: `saki-controlplane/db/migrations/000070_asset_tables.sql`
- Create: `saki-controlplane/db/migrations/000071_asset_durable_upload.sql`
- Modify: `saki-controlplane/db/queries/asset/asset.sql`
- Create: `saki-controlplane/db/queries/asset/asset_reference.sql`
- Create: `saki-controlplane/db/queries/asset/asset_upload_intent.sql`
- Modify: `saki-controlplane/internal/modules/asset/repo/asset_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/reference_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/upload_intent_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/durable_upload_tx_runner.go`
- Modify: `saki-controlplane/internal/modules/asset/repo/repo_test.go`
- Create: `saki-controlplane/internal/modules/asset/repo/durable_upload_repo_test.go`
- Create: `saki-controlplane/internal/modules/asset/app/types.go`
- Create: `saki-controlplane/internal/modules/asset/app/owner_resolver.go`
- Create: `saki-controlplane/internal/modules/asset/app/durable_upload.go`
- Create: `saki-controlplane/internal/modules/asset/app/durable_upload_test.go`
- Create: `saki-controlplane/internal/modules/asset/app/stale_pending_cleaner.go`
- Create: `saki-controlplane/internal/modules/asset/app/stale_pending_cleaner_test.go`
- Create: `saki-controlplane/internal/modules/asset/adapters/owner_resolver.go`
- Create: `saki-controlplane/internal/modules/asset/adapters/owner_resolver_test.go`
- Modify: `saki-controlplane/internal/modules/asset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/asset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-controlplane/internal/gen/sqlc/*`
- Modify: `saki-controlplane/internal/gen/openapi/*`

## Chunk 1: Schema And Persistence

### Task 1: 收敛 asset schema，并为 durable upload 建表

**Files:**
- Modify: `saki-controlplane/db/migrations/000070_asset_tables.sql`
- Create: `saki-controlplane/db/migrations/000071_asset_durable_upload.sql`
- Modify: `saki-controlplane/internal/modules/asset/repo/repo_test.go`
- Test: `saki-controlplane/internal/modules/asset/repo/repo_test.go`

- [ ] **Step 1: 先写失败测试，锁定 schema contract**

在 [repo_test.go](/Users/hhm/code/saki/saki-controlplane/internal/modules/asset/repo/repo_test.go) 增补至少这些测试：

```go
func TestAssetSchemaIncludesReadyAtAndOrphanedAt(t *testing.T) {}
func TestAssetSchemaUsesStorageScopedUniqueKey(t *testing.T) {}
func TestAssetDurableUploadTablesExist(t *testing.T) {}
func TestAssetUploadIntentUsesCascadeDelete(t *testing.T) {}
```

检查项至少包括：

```sql
asset.ready_at
asset.orphaned_at
unique(storage_backend, bucket, object_key)
asset_reference
asset_upload_intent
asset_upload_intent.asset_id references asset(id) on delete cascade
```

- [ ] **Step 2: 运行 repo schema 测试，确认当前 migration 还不满足切片要求**

Run: `cd saki-controlplane && go test ./internal/modules/asset/repo -run 'TestAssetSchema|TestAssetDurableUploadTablesExist|TestAssetUploadIntentUsesCascadeDelete' -v`

Expected: FAIL，原因是当前 `asset` 只有基础表，没有 `ready_at / orphaned_at / asset_reference / asset_upload_intent`。

- [ ] **Step 3: 实现 migration**

要求：

1. `000070_asset_tables.sql` 只做兼容性最小修补时才修改；新结构尽量放到 `000071_asset_durable_upload.sql`。
2. `asset.kind / status / storage_backend` 从宽松 text 收敛成 PostgreSQL enum 或等价强约束。
3. `asset` 增加 `ready_at`、`orphaned_at`，并把唯一键收紧为 `(storage_backend, bucket, object_key)`。
4. 新增 `asset_reference` 与 `asset_upload_intent`，按 spec 建唯一约束与非唯一索引。
5. `asset_upload_intent` 必须包含 `declared_content_type`，并用 `on delete cascade` 绑定 `asset_id`。

- [ ] **Step 4: 重新运行 schema 测试**

Run: `cd saki-controlplane && go test ./internal/modules/asset/repo -run 'TestAssetSchema|TestAssetDurableUploadTablesExist|TestAssetUploadIntentUsesCascadeDelete' -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/db/migrations/000070_asset_tables.sql \
  saki-controlplane/db/migrations/000071_asset_durable_upload.sql \
  saki-controlplane/internal/modules/asset/repo/repo_test.go
git commit -m "feat(asset): add durable upload schema"
```

### Task 2: 生成 sqlc query，并补齐 repo/tx 持久化能力

**Files:**
- Modify: `saki-controlplane/db/queries/asset/asset.sql`
- Create: `saki-controlplane/db/queries/asset/asset_reference.sql`
- Create: `saki-controlplane/db/queries/asset/asset_upload_intent.sql`
- Modify: `saki-controlplane/internal/modules/asset/repo/asset_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/reference_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/upload_intent_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/durable_upload_tx_runner.go`
- Create: `saki-controlplane/internal/modules/asset/repo/durable_upload_repo_test.go`
- Modify: `saki-controlplane/internal/gen/sqlc/*`
- Test: `saki-controlplane/internal/modules/asset/repo/durable_upload_repo_test.go`
- Test: `saki-controlplane/internal/modules/asset/repo/repo_test.go`

- [ ] **Step 1: 写失败测试，锁定 repo 行为**

新增至少这些测试：

```go
func TestUploadIntentRepoCreateGetAndMarkExpired(t *testing.T) {}
func TestDurableUploadRepoCreateReferenceAndMaintainOrphanedAt(t *testing.T) {}
func TestDurableUploadRepoListStalePendingAssets(t *testing.T) {}
func TestDurableUploadRepoDeleteAssetCascadesIntent(t *testing.T) {}
func TestDurableUploadRepoRetriesObjectKeyCollision(t *testing.T) {}
```

repo contract 至少要覆盖：

```go
type DurableUploadTx interface {
    CreatePendingAsset(...)
    GetAsset(...)
    GetUploadIntentByAssetID(...)
    GetUploadIntentByOwnerKey(...)
    CreateUploadIntent(...)
    MarkUploadIntentCompleted(...)
    MarkUploadIntentCanceled(...)
    MarkUploadIntentExpired(...)
    CreateDurableReference(...)
    ListActiveReferencesByOwner(...)
    ListStalePendingAssets(...)
    DeleteAsset(...)
}
```

- [ ] **Step 2: 运行 repo 测试，确认 query/repo 接口还不存在**

Run: `cd saki-controlplane && go test ./internal/modules/asset/repo -run 'TestUploadIntentRepo|TestDurableUploadRepo' -v`

Expected: FAIL

- [ ] **Step 3: 实现 sql query、repo 与 tx runner**

要求：

1. `asset.sql` 要补 `ready_at / orphaned_at / storage_backend` 相关列，并显式支持 finalize 更新 `size_bytes / sha256_hex / content_type / ready_at`。
2. `asset_reference.sql` 至少提供 `CreateDurableReference`、`ListActiveReferencesByOwner`、`InvalidateReferencesForOwner`、`CountActiveReferencesForAsset`。
3. `asset_upload_intent.sql` 至少提供按 `asset_id`、按 `(owner_type, owner_id, role, idempotency_key)` 查询，以及 `completed / canceled / expired` 状态变更。
4. tx runner 模式沿用 [tx.go](/Users/hhm/code/saki/saki-controlplane/internal/app/db/tx.go) 与 runtime command 的做法，不要把多表事务散到 handler。
5. repo 层只做持久化与数据库一致性，不夹杂 owner 业务判定。

- [ ] **Step 4: 生成 sqlc，并跑 repo 测试**

Run: `cd saki-controlplane && make gen-sqlc && go test ./internal/modules/asset/repo -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/db/queries/asset/asset.sql \
  saki-controlplane/db/queries/asset/asset_reference.sql \
  saki-controlplane/db/queries/asset/asset_upload_intent.sql \
  saki-controlplane/internal/modules/asset/repo/asset_repo.go \
  saki-controlplane/internal/modules/asset/repo/reference_repo.go \
  saki-controlplane/internal/modules/asset/repo/upload_intent_repo.go \
  saki-controlplane/internal/modules/asset/repo/durable_upload_tx_runner.go \
  saki-controlplane/internal/modules/asset/repo/durable_upload_repo_test.go \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(asset): add durable upload persistence layer"
```

## Chunk 2: Application Usecases

### Task 3: 建立 typed model 与 owner resolver adapter

**Files:**
- Create: `saki-controlplane/internal/modules/asset/app/types.go`
- Create: `saki-controlplane/internal/modules/asset/app/owner_resolver.go`
- Create: `saki-controlplane/internal/modules/asset/adapters/owner_resolver.go`
- Create: `saki-controlplane/internal/modules/asset/adapters/owner_resolver_test.go`
- Test: `saki-controlplane/internal/modules/asset/adapters/owner_resolver_test.go`

- [ ] **Step 1: 写失败测试，锁定 owner resolution 与 enum 收敛**

```go
func TestOwnerResolverResolvesProjectDatasetAndSample(t *testing.T) {}
func TestOwnerResolverRejectsUnsupportedOwnerType(t *testing.T) {}
func TestOwnerTypeRolePrimaryValidation(t *testing.T) {}
```

应用层类型至少包括：

```go
type AssetKind string
type AssetStatus string
type AssetStorageBackend string
type AssetOwnerType string
type AssetReferenceRole string
type AssetUploadIntentState string

type DurableOwnerBinding struct {
    OwnerType AssetOwnerType
    OwnerID uuid.UUID
    Role AssetReferenceRole
    IsPrimary bool
}
```

- [ ] **Step 2: 运行 adapter/app 测试，确认类型与 resolver 还不存在**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app ./internal/modules/asset/adapters -run 'TestOwnerResolver|TestOwnerTypeRolePrimaryValidation' -v`

Expected: FAIL

- [ ] **Step 3: 实现 typed model 与 resolver**

要求：

1. 把能收敛成 enum 的字符串全部收成常量/强类型，不再让 usecase 直接吃裸字符串。
2. `OwnerResolver` 只回答 owner 是否存在，以及 sample 对应的 dataset 关联是否存在；不要在这里实现 durable upload 状态机。
3. resolver adapter 可以直接用 sqlc query 或最小 getter 接口，但不要把 `asset/app` 直接 import 到 `project/dataset/annotation` repo。
4. `sample` 解析要基于 [sample_repo.go](/Users/hhm/code/saki/saki-controlplane/internal/modules/annotation/repo/sample_repo.go) 的真相，即 sample 归属于 dataset。

- [ ] **Step 4: 运行测试**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app ./internal/modules/asset/adapters -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/asset/app/types.go \
  saki-controlplane/internal/modules/asset/app/owner_resolver.go \
  saki-controlplane/internal/modules/asset/adapters/owner_resolver.go \
  saki-controlplane/internal/modules/asset/adapters/owner_resolver_test.go
git commit -m "feat(asset): add durable owner typing and resolver"
```

### Task 4: 实现 durable upload init/complete/cancel 状态机

**Files:**
- Create: `saki-controlplane/internal/modules/asset/app/durable_upload.go`
- Create: `saki-controlplane/internal/modules/asset/app/durable_upload_test.go`
- Test: `saki-controlplane/internal/modules/asset/app/durable_upload_test.go`

- [ ] **Step 1: 写失败测试，锁定核心用例**

至少覆盖这些测试：

```go
func TestInitDurableUploadCreatesPendingAssetAndIntent(t *testing.T) {}
func TestInitDurableUploadReplaysInitiatedIntent(t *testing.T) {}
func TestInitDurableUploadRejectsMismatchedIdempotencyContract(t *testing.T) {}
func TestCompleteDurableUploadCreatesReferenceAtomically(t *testing.T) {}
func TestCompleteDurableUploadReplaysCompletedIntent(t *testing.T) {}
func TestCompleteDurableUploadRejectsExpiredIntent(t *testing.T) {}
func TestCompleteDurableUploadFailsOnPrimaryConflict(t *testing.T) {}
func TestCancelDurableUploadMarksIntentCanceled(t *testing.T) {}
```

init/complete usecase 输入结构建议固定为：

```go
type InitDurableUploadInput struct {
    Binding DurableOwnerBinding
    Kind AssetKind
    DeclaredContentType string
    Metadata []byte
    IdempotencyKey string
    CreatedBy *uuid.UUID
}

type CompleteDurableUploadInput struct {
    AssetID uuid.UUID
    RequestSizeBytes *int64
    SHA256Hex *string
}
```

- [ ] **Step 2: 运行 app 测试，确认状态机还不存在**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app -run 'TestInitDurableUpload|TestCompleteDurableUpload|TestCancelDurableUpload' -v`

Expected: FAIL

- [ ] **Step 3: 实现 durable upload usecase**

要求：

1. `InitDurableUpload` 必须拥有主事务，先 resolve owner，再处理 idempotency，再决定是否创建新 asset/intent。
2. 相同 `(owner_type, owner_id, role, idempotency_key)`：
   - `initiated && expires_at > now` 时 replay 同一 `asset_id` 并重签 upload ticket。
   - `initiated && expires_at <= now` 时先视为 `expired`，然后返回冲突。
   - `completed` 时返回最终状态，不再发新 ticket。
   - `canceled/expired` 时返回冲突。
3. `CompleteDurableUpload` 必须在一个事务里完成 remote object 校验、owner re-check、唯一性冲突判定、asset finalize、reference 创建、intent 完成。
4. `sample + primary` 与一般 `is_primary=true` 冲突只在 complete 收口，不在 init 预占。
5. finalize 时必须把 provider 探测出的 `size_bytes` 落到 `asset.size_bytes`。

- [ ] **Step 4: 运行 app 测试**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/asset/app/durable_upload.go \
  saki-controlplane/internal/modules/asset/app/durable_upload_test.go
git commit -m "feat(asset): implement durable upload usecases"
```

### Task 5: 实现 stale pending cleaner 与 public-api 内最小后台循环

**Files:**
- Create: `saki-controlplane/internal/modules/asset/app/stale_pending_cleaner.go`
- Create: `saki-controlplane/internal/modules/asset/app/stale_pending_cleaner_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Test: `saki-controlplane/internal/modules/asset/app/stale_pending_cleaner_test.go`
- Test: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`

- [ ] **Step 1: 写失败测试，锁定 cleaner contract**

```go
func TestStalePendingCleanerDeletesOnlyPastGraceWindowAssets(t *testing.T) {}
func TestStalePendingCleanerDeletesAssetAndCascadesIntent(t *testing.T) {}
func TestPublicAPIBootstrapStartsAndStopsAssetCleaner(t *testing.T) {}
```

- [ ] **Step 2: 运行 cleaner/bootstrap 测试，确认清理器还不存在**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app ./internal/app/bootstrap -run 'TestStalePendingCleaner|TestPublicAPIBootstrapStartsAndStopsAssetCleaner' -v`

Expected: FAIL

- [ ] **Step 3: 实现 cleaner 与 bootstrap wiring**

要求：

1. cleaner 判定必须只看 `asset.created_at + upload_grace_window`，不能从 `canceled_at` 或 `expired_at` 重新起表。
2. 删除顺序按 spec：先最佳努力删对象，再删 `asset`，由 `on delete cascade` 清掉 intent。
3. `bootstrap.NewPublicAPI` 用 `context.WithCancel(ctx)` 启动最小后台循环，并在 `server.RegisterOnShutdown` 中停止，避免 goroutine 泄漏。
4. cleaner 失败只记日志，不要让 public API 直接退出。

- [ ] **Step 4: 运行测试**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app ./internal/app/bootstrap -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/asset/app/stale_pending_cleaner.go \
  saki-controlplane/internal/modules/asset/app/stale_pending_cleaner_test.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/app/bootstrap/bootstrap_test.go
git commit -m "feat(asset): add stale pending cleaner"
```

## Chunk 3: Public API And Integration

### Task 6: 扩展 `/assets` API 为 durable upload 最小入口

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/internal/modules/asset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/asset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/gen/openapi/*`
- Test: `saki-controlplane/internal/modules/asset/apihttp/handlers_test.go`

- [ ] **Step 1: 写失败测试，锁定新的 API contract**

至少补这些 handler 测试：

```go
func TestInitAssetUploadRequiresOwnerBindingAndIdempotencyKey(t *testing.T) {}
func TestInitAssetUploadReplaysCompletedIntentWithoutUploadURL(t *testing.T) {}
func TestCompleteAssetUploadUsesDurableUseCase(t *testing.T) {}
func TestCancelAssetUploadCancelsInitiatedIntent(t *testing.T) {}
```

OpenAPI 最小变更建议：

```yaml
AssetUploadInitRequest:
  required:
    - owner_type
    - owner_id
    - role
    - is_primary
    - idempotency_key
    - kind
    - content_type
    - metadata

AssetUploadInitResponse:
  required:
    - asset
    - intent_state
  properties:
    upload_url:
      type: string
      nullable: true
    expires_in:
      type: integer
      format: int32
      nullable: true

/assets/{asset_id}:cancel:
  post:
    operationId: cancelAssetUpload
```

- [ ] **Step 2: 运行 API 测试，确认当前 handler 无法承载 owner/intention 语义**

Run: `cd saki-controlplane && go test ./internal/modules/asset/apihttp -run 'TestInitAssetUpload|TestCompleteAssetUpload|TestCancelAssetUpload' -v`

Expected: FAIL

- [ ] **Step 3: 修改 OpenAPI、handler 与 system server**

要求：

1. 本轮继续沿用 `/assets/...` 路由，不在这里引入 `/projects/{id}/assets` 一类最终 owner-scoped API。
2. handler 只负责鉴权、参数解析、调用 usecase、映射错误，不直接自己操作 repo。
3. `init` 需要支持：
   - 新建上传时返回 `upload_url`
   - `completed` replay 时不返回 `upload_url`
4. `complete` 继续走 `asset_id` 路由，owner 绑定来自 intent 真相，而不是客户端重复提交。
5. `cancel` 必须成为显式 API，而不是仅靠后台过期。

- [ ] **Step 4: 生成 openapi，并跑 API 测试**

Run: `cd saki-controlplane && make gen-openapi && go test ./internal/modules/asset/apihttp -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/openapi/public-api.yaml \
  saki-controlplane/internal/modules/asset/apihttp/handlers.go \
  saki-controlplane/internal/modules/asset/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/system/apihttp/server.go \
  saki-controlplane/internal/gen/openapi
git commit -m "feat(asset): expose durable upload api"
```

### Task 7: 接入 bootstrap、权限与 smoke 覆盖

**Files:**
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`

- [ ] **Step 1: 写失败 smoke/boot 测试，锁定整链路**

新增或改造 smoke 用例至少覆盖：

```go
func TestPublicAPISmoke_DurableAssetUploadLifecycle(t *testing.T) {}
func TestPublicAPISmoke_DurableAssetUploadCancel(t *testing.T) {}
```

链路至少包含：

1. `init` 传入 owner 绑定与 `idempotency_key`
2. PUT 对象到 MinIO mock
3. `complete` 后 asset 变为 `ready`
4. 重复 `complete` replay 成功
5. `cancel` 后不能再 `complete`

- [ ] **Step 2: 运行 smoke/bootstrap 测试，确认 wiring 尚未完成**

Run: `cd saki-controlplane && go test ./internal/app/bootstrap ./internal/modules/system/apihttp -run 'TestPublicAPISmoke|TestBootstrap' -v`

Expected: FAIL

- [ ] **Step 3: 完成 wiring**

要求：

1. bootstrap 中构造 durable upload usecase、owner resolver adapter、cleaner loop。
2. 权限至少映射为：
   - `project` owner -> `projects:write`
   - `dataset` owner -> `datasets:write`
   - `sample` owner -> `datasets:write`
3. smoke fixture 里补 `datasets:write`，避免只靠 `assets:write` 放行。
4. 所有 wiring 都保持在 `public-api` 进程内，不影响 runtime 进程。

- [ ] **Step 4: 运行 smoke 与集成测试**

Run: `cd saki-controlplane && go test ./internal/app/bootstrap ./internal/modules/system/apihttp -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/app/bootstrap/bootstrap_test.go \
  saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go
git commit -m "feat(asset): wire durable upload into public api"
```

## Chunk 4: Final Verification

### Task 8: 全量验证并整理提交边界

**Files:**
- Modify: `saki-controlplane/internal/gen/sqlc/*`
- Modify: `saki-controlplane/internal/gen/openapi/*`

- [ ] **Step 1: 运行资产切片回归**

Run:

```bash
cd saki-controlplane
make gen
go test ./internal/modules/asset/... -v
go test ./internal/app/bootstrap ./internal/modules/system/apihttp -v
```

Expected: PASS

- [ ] **Step 2: 跑一次更宽的 controlplane 回归**

Run:

```bash
cd saki-controlplane
go test ./internal/modules/dataset/... ./internal/modules/project/... ./internal/modules/annotation/... ./internal/modules/importing/... -v
```

Expected: PASS；如果有失败，先确认是否是这次 API/权限改动引起的真实回归。

- [ ] **Step 3: 检查 git 变更边界**

Run:

```bash
git status --short
```

Expected:

1. 只包含本计划涉及的 asset / bootstrap / openapi / sqlc 变更。
2. [runtime_task_lifecycle_test.go](/Users/hhm/code/saki/saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go) 仍保持单独未提交状态，不混入本切片提交。

- [ ] **Step 4: 提交最终切片**

```bash
git add \
  saki-controlplane/db/migrations \
  saki-controlplane/db/queries/asset \
  saki-controlplane/internal/modules/asset \
  saki-controlplane/internal/app/bootstrap \
  saki-controlplane/internal/modules/system/apihttp \
  saki-controlplane/api/openapi/public-api.yaml \
  saki-controlplane/internal/gen/sqlc \
  saki-controlplane/internal/gen/openapi
git commit -m "feat(asset): add durable upload ownership slice"
```
