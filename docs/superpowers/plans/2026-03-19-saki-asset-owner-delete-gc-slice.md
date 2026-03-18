# Saki Asset Owner Delete GC Slice Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `saki-controlplane` 中补上 asset 生命周期的下一最小闭环：`dataset` 删除时同事务失效 `dataset/sample` durable reference，并为 `ready + orphaned` asset 上线 retention GC。

**Architecture:** 保持 `asset` 作为物理对象真相层，owner 删除仍由 owner 模块发起事务。`dataset` 删除改为走 tx runner，在同一事务内先收集 sample owner，再失效 `dataset/sample` 的 durable reference，最后删除 dataset；`asset` 侧新增 `ready orphan` 查询与 cleaner，并与现有 stale pending 清理统一接到 public-api 后台循环。

**Tech Stack:** Go, PostgreSQL, sqlc, pgx/v5, testcontainers-go, MinIO provider interface

---

## Planned Files

- Modify: `saki-controlplane/db/queries/annotation/sample.sql`
- Modify: `saki-controlplane/db/queries/asset/asset.sql`
- Modify: `saki-controlplane/internal/modules/annotation/repo/sample_repo.go`
- Modify: `saki-controlplane/internal/modules/asset/repo/asset_repo.go`
- Create: `saki-controlplane/internal/modules/dataset/app/delete_dataset.go`
- Create: `saki-controlplane/internal/modules/dataset/repo/delete_dataset_tx_runner.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Create: `saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner.go`
- Create: `saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-controlplane/internal/gen/sqlc/*`

## Chunk 1: Dataset Delete Transaction

### Task 1: 让 dataset 删除在同一事务内失效 dataset/sample 的 durable reference

**Files:**
- Modify: `saki-controlplane/db/queries/annotation/sample.sql`
- Modify: `saki-controlplane/internal/modules/annotation/repo/sample_repo.go`
- Create: `saki-controlplane/internal/modules/dataset/app/delete_dataset.go`
- Create: `saki-controlplane/internal/modules/dataset/repo/delete_dataset_tx_runner.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/gen/sqlc/*`
- Test: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`

- [ ] **Step 1: 先写失败测试，锁定 dataset 删除的 asset 生命周期行为**

至少补这些测试：

```go
func TestDeleteDatasetInvalidatesDatasetAndSampleAssetReferences(t *testing.T) {}
func TestDeleteDatasetMissingDatasetDoesNotTouchAssetReferences(t *testing.T) {}
```

测试检查点至少包括：

1. 删除 dataset 前，为同一个 dataset 建立一条 `owner_type=dataset` durable reference，并为该 dataset 下 sample 建一条 `owner_type=sample` durable reference。
2. 删除 dataset 后，两条 reference 都被写入 `deleted_at`。
3. 若对应 asset 因此失去最后一个 active reference，则 `asset.orphaned_at` 在同一事务中被写入。
4. 删除不存在的 dataset 返回 `404`，且已有 reference 不被误失效。

- [ ] **Step 2: 运行 dataset 删除测试，确认当前实现还只是裸 delete**

Run: `cd saki-controlplane && go test ./internal/modules/dataset/apihttp -run 'TestDeleteDatasetInvalidatesDatasetAndSampleAssetReferences|TestDeleteDatasetMissingDatasetDoesNotTouchAssetReferences' -v`

Expected: FAIL，原因是当前 `DeleteDatasetUseCase` 直接调用 repo delete，没有 tx runner，也不会失效 sample owner reference。

- [ ] **Step 3: 实现 dataset 删除 tx runner 与 usecase**

要求：

1. 新增 `ListSampleIDsByDataset` query，删除前先取出当前 dataset 下的 sample id 集合。
2. `DeleteDatasetUseCase` 改为依赖专用 tx runner，而不是复用通用 CRUD store。
3. 同一事务内执行顺序固定为：
   - 确认 dataset 存在
   - 读取 sample ids
   - 失效 `owner_type=dataset, owner_id=dataset_id`
   - 逐个失效 `owner_type=sample, owner_id in sample_ids`
   - 删除 dataset
4. 若事务中任一步失败，dataset 删除与 reference 失效必须整体回滚。
5. 非 durable / 非当前 owner 的 reference 不应被误改。

- [ ] **Step 4: 重新运行 dataset 删除测试**

Run: `cd saki-controlplane && go test ./internal/modules/dataset/apihttp -run 'TestDeleteDatasetInvalidatesDatasetAndSampleAssetReferences|TestDeleteDatasetMissingDatasetDoesNotTouchAssetReferences' -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/db/queries/annotation/sample.sql \
  saki-controlplane/internal/modules/annotation/repo/sample_repo.go \
  saki-controlplane/internal/modules/dataset/app/delete_dataset.go \
  saki-controlplane/internal/modules/dataset/repo/delete_dataset_tx_runner.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(dataset): invalidate asset references on delete"
```

## Chunk 2: Ready Orphan GC

### Task 2: 为 ready orphan asset 增加 retention GC

**Files:**
- Modify: `saki-controlplane/db/queries/asset/asset.sql`
- Modify: `saki-controlplane/internal/modules/asset/repo/asset_repo.go`
- Create: `saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner.go`
- Create: `saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner_test.go`
- Modify: `saki-controlplane/internal/gen/sqlc/*`
- Test: `saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner_test.go`

- [ ] **Step 1: 先写失败测试，锁定 ready orphan cleaner contract**

至少补这些测试：

```go
func TestReadyOrphanCleanerDeletesOnlyAssetsPastRetentionWindow(t *testing.T) {}
func TestReadyOrphanCleanerIgnoresAssetsWithActiveReferences(t *testing.T) {}
func TestReadyOrphanCleanerTreatsMissingObjectAsBestEffortDelete(t *testing.T) {}
```

检查点至少包括：

1. 只清理 `status=ready` 且 `orphaned_at <= now-retention_window` 的 asset。
2. 仍有 active reference 的 asset 即使 `orphaned_at` 非空也不清理。
3. 删除对象存储内容后再删 `asset` 行；对象已不存在时按 best effort 继续。

- [ ] **Step 2: 运行 cleaner 测试，确认 ready orphan GC 尚不存在**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app -run 'TestReadyOrphanCleaner' -v`

Expected: FAIL

- [ ] **Step 3: 实现 query、repo 与 cleaner**

要求：

1. `asset.sql` 新增 `ListReadyOrphanedAssets`，按 `status=ready`、`orphaned_at` 截止时间、且无 active reference 判定。
2. `asset_repo.go` 暴露对应 repo 方法，复用现有 `Asset` 转换逻辑。
3. cleaner 与现有 stale pending cleaner 保持相同容错语义：
   - 先 best effort 删对象
   - 再删 asset 行
   - `storage.ErrObjectNotFound` 不算失败
4. retention 锚点只看 `orphaned_at`，不能回退到 `updated_at`。

- [ ] **Step 4: 重新运行 cleaner 测试**

Run: `cd saki-controlplane && go test ./internal/modules/asset/app -run 'TestReadyOrphanCleaner' -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/db/queries/asset/asset.sql \
  saki-controlplane/internal/modules/asset/repo/asset_repo.go \
  saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner.go \
  saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner_test.go \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(asset): add ready orphan cleaner"
```

## Chunk 3: Bootstrap Wiring And Verification

### Task 3: 把 ready orphan GC 接进 public-api，并做最小回归

**Files:**
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Test: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Test: `saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go`

- [ ] **Step 1: 先写失败测试，锁定 bootstrap wiring**

至少补这些测试：

```go
func TestPublicAPIBootstrapStartsCombinedAssetCleaner(t *testing.T) {}
```

如果沿用现有 test seam，也可以把旧的 cleaner loop 启停测试扩成“包含 stale pending 与 ready orphan 的统一清理循环已启动”。

- [ ] **Step 2: 运行 bootstrap 测试，确认 wiring 还没覆盖 ready orphan cleaner**

Run: `cd saki-controlplane && go test ./internal/app/bootstrap -run 'TestPublicAPIBootstrapStarts' -v`

Expected: FAIL

- [ ] **Step 3: 实现 public-api wiring**

要求：

1. public-api 只在对象存储 provider 存在时启动 asset cleaner loop。
2. loop 中同时执行 stale pending cleaner 与 ready orphan cleaner。
3. 缺少对象存储配置时仍允许 public-api 启动；该行为不得回归。

- [ ] **Step 4: 跑最小回归**

Run:

```bash
cd saki-controlplane
go test ./internal/app/bootstrap ./internal/modules/dataset/apihttp ./internal/modules/asset/app -v
```

Expected: PASS

- [ ] **Step 5: 检查提交边界并提交**

Run:

```bash
git status --short
```

Expected:

1. 只包含本切片相关的 dataset / asset / bootstrap / sqlc 变更。
2. `saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go` 与既有 docs 未提交改动仍保持独立。

Commit:

```bash
git add \
  saki-controlplane/db/queries/annotation/sample.sql \
  saki-controlplane/db/queries/asset/asset.sql \
  saki-controlplane/internal/modules/annotation/repo/sample_repo.go \
  saki-controlplane/internal/modules/dataset/app/delete_dataset.go \
  saki-controlplane/internal/modules/dataset/repo/delete_dataset_tx_runner.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers.go \
  saki-controlplane/internal/modules/dataset/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/asset/repo/asset_repo.go \
  saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner.go \
  saki-controlplane/internal/modules/asset/app/ready_orphan_cleaner_test.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/app/bootstrap/bootstrap_test.go \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(asset): wire owner delete and ready orphan gc"
```
