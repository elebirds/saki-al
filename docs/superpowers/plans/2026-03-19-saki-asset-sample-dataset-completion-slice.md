# Saki Asset Sample Dataset Completion Slice Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `saki-controlplane` 中补齐 `sample` 与 `dataset` 层的 asset 生命周期闭环，确保 `sample` 删除、`dataset` 删除和 durable asset 引用语义在当前业务范围内可用且一致。

**Architecture:** 保持 `asset` 作为物理对象真相层，`sample` 仍视为 `dataset` 的子资源，不扩展成完整独立 CRUD 模块。新增最小 `sample delete` 事务路径，在同一事务内校验 `dataset/sample` 归属、失效 `sample` durable reference、删除 `sample` 真相；`dataset` 侧只补共享资产与级联一致性回归，不扩展到 `project` 或 owner-scoped asset API。

**Tech Stack:** Go, PostgreSQL, sqlc, pgx/v5, ogen/OpenAPI, testcontainers-go

---

## Planned Files

- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/db/queries/annotation/sample.sql`
- Modify: `saki-controlplane/internal/modules/annotation/repo/sample_repo.go`
- Create: `saki-controlplane/internal/modules/dataset/app/delete_sample.go`
- Create: `saki-controlplane/internal/modules/dataset/app/delete_sample_repo_adapter.go`
- Create: `saki-controlplane/internal/modules/dataset/repo/delete_sample_tx_runner.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/internal/gen/openapi/*`
- Modify: `saki-controlplane/internal/gen/sqlc/*`

## Chunk 1: Sample Delete Lifecycle

### Task 1: 为 sample 建立最小删除入口，并在同一事务内失效 durable reference

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/db/queries/annotation/sample.sql`
- Modify: `saki-controlplane/internal/modules/annotation/repo/sample_repo.go`
- Create: `saki-controlplane/internal/modules/dataset/app/delete_sample.go`
- Create: `saki-controlplane/internal/modules/dataset/app/delete_sample_repo_adapter.go`
- Create: `saki-controlplane/internal/modules/dataset/repo/delete_sample_tx_runner.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/gen/openapi/*`
- Modify: `saki-controlplane/internal/gen/sqlc/*`
- Test: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`

- [ ] **Step 1: 先写失败测试，锁定 sample 删除 contract**

至少补这些测试：

```go
func TestDeleteDatasetSampleInvalidatesSampleAssetReferences(t *testing.T) {}
func TestDeleteDatasetSampleKeepsAssetLiveWhenOtherOwnerReferencesRemain(t *testing.T) {}
func TestDeleteDatasetSampleRejectsDatasetSampleMismatch(t *testing.T) {}
func TestDeleteDatasetSampleReturnsNotFoundForMissingSample(t *testing.T) {}
```

检查点至少包括：

1. `DELETE /datasets/{dataset_id}/samples/{sample_id}` 成功后，`owner_type=sample` 的 active durable reference 被写入 `deleted_at`。
2. 若该 sample asset 因此失去最后一个 active reference，则 `asset.orphaned_at` 在同一事务中写入。
3. 若同一 asset 还有 `project` 或 `dataset` 等其他 active owner，则只失效 sample 引用，不把 asset 误标为 orphan。
4. `sample.dataset_id != path dataset_id` 时必须拒绝，不能误删跨 dataset 的 sample。
5. `annotation` 与 `sample_match_ref` 依赖现有 FK 级联删除，不需要额外手写删除逻辑。

- [ ] **Step 2: 运行 sample 删除测试，确认当前实现缺口真实存在**

Run:

```bash
cd saki-controlplane
go test ./internal/modules/dataset/apihttp -run 'TestDeleteDatasetSample' -v
```

Expected: FAIL，因为当前没有 sample 删除路由、用例和 tx runner。

- [ ] **Step 3: 实现 sample 删除 tx runner、use case 与最小 API**

要求：

1. `sample` 仍作为 `dataset` 子资源，由 `dataset` 模块暴露最小删除入口，不扩展 list/get/create 产品面。
2. 新增 sample 查询/删除 SQL，至少支持：
   - 按 `sample_id` 读取 `dataset_id`
   - `SELECT ... FOR UPDATE` 锁定 sample 真相
   - 删除 sample
3. 同一事务内执行顺序固定为：
   - 锁定并读取 sample
   - 校验 `sample.dataset_id == path dataset_id`
   - 失效 `owner_type=sample, owner_id=sample_id`
   - 删除 sample
4. 若引用失效失败，则 sample 删除整体回滚。
5. 不手工删除 `annotation`、`sample_match_ref`，继续依赖 FK cascade。
6. bootstrap 和 HTTP server 需要把新用例装配进去，但不影响现有 dataset delete 路径。

- [ ] **Step 4: 重新运行 sample 删除测试**

Run:

```bash
cd saki-controlplane
go test ./internal/modules/dataset/apihttp -run 'TestDeleteDatasetSample' -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/openapi/public-api.yaml \
  saki-controlplane/db/queries/annotation/sample.sql \
  saki-controlplane/internal/modules/annotation/repo/sample_repo.go \
  saki-controlplane/internal/modules/dataset/app/delete_sample.go \
  saki-controlplane/internal/modules/dataset/app/delete_sample_repo_adapter.go \
  saki-controlplane/internal/modules/dataset/repo/delete_sample_tx_runner.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/system/apihttp/server.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/gen/openapi \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(dataset): add sample delete lifecycle"
```

## Chunk 2: Dataset Completion Regressions

### Task 2: 补齐 sample/dataset 层共享资产与级联一致性回归

**Files:**
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Test: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`

- [ ] **Step 1: 先补失败测试，锁定“这一层基本完工”的验收线**

至少覆盖：

```go
func TestDeleteDatasetInvalidatesSampleOwnedAssetsBeforeCascade(t *testing.T) {}
func TestDeleteDatasetSampleAndDatasetDeleteShareConsistentOrphanSemantics(t *testing.T) {}
```

若现有测试已经覆盖同一行为，则改为增强断言，不重复造同义测试。

检查点至少包括：

1. `dataset delete` 与 `sample delete` 对共享 asset 的 orphan 判定一致。
2. `dataset delete` 仍能在 sample FK 级联发生前，先失效 sample durable reference。
3. 新增的 sample 删除入口不会回归现有 dataset delete 场景。

- [ ] **Step 2: 运行 dataset 回归测试，确认旧实现未覆盖完整一致性**

Run:

```bash
cd saki-controlplane
go test ./internal/modules/dataset/apihttp -run 'TestDeleteDataset|TestDeleteDatasetSample' -v
```

Expected: 若新增断言命中缺口则 FAIL；否则进入最小实现调整。

- [ ] **Step 3: 做最小修正并保持语义一致**

要求：

1. 优先复用已有 dataset delete / asset orphan 逻辑，不重写一套新规则。
2. 如需要共享帮助函数，只做小范围抽取，避免把 dataset handler 变成通用 owner-delete 框架。
3. 不引入 `project` 侧逻辑。

- [ ] **Step 4: 重新运行 dataset 回归测试**

Run:

```bash
cd saki-controlplane
go test ./internal/modules/dataset/apihttp -run 'TestDeleteDataset|TestDeleteDatasetSample' -v
```

Expected: PASS

## Chunk 3: Integrated Verification

### Task 3: 做 sample/dataset 完整验证并检查提交边界

**Files:**
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Test: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Test: `saki-controlplane/internal/modules/asset/...`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Test: `saki-controlplane/internal/app/bootstrap`

- [ ] **Step 1: 为新 sample 删除路径补最小 smoke 覆盖**

至少包含：

1. 通过 public API 创建 dataset / seed sample。
2. 调用新 sample 删除接口。
3. 确认返回码与后续读取/级联行为符合预期。

- [ ] **Step 2: 运行最小集成验证**

Run:

```bash
cd saki-controlplane
go test ./internal/modules/dataset/... ./internal/modules/asset/... ./internal/modules/system/apihttp ./internal/app/bootstrap -v
```

Expected: PASS

- [ ] **Step 3: 检查工作树边界**

Run:

```bash
git status --short
```

Expected:

1. 只包含本切片相关的 `sample/dataset/asset/openapi/sqlc/bootstrap` 变更。
2. `saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go` 与既有 docs 草稿保持独立，不混入提交。

- [ ] **Step 4: Commit**

```bash
git add \
  saki-controlplane/api/openapi/public-api.yaml \
  saki-controlplane/db/queries/annotation/sample.sql \
  saki-controlplane/internal/modules/annotation/repo/sample_repo.go \
  saki-controlplane/internal/modules/dataset/app/delete_sample.go \
  saki-controlplane/internal/modules/dataset/app/delete_sample_repo_adapter.go \
  saki-controlplane/internal/modules/dataset/repo/delete_sample_tx_runner.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/system/apihttp/server.go \
  saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/gen/openapi \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(asset): complete sample and dataset lifecycle slice"
```
