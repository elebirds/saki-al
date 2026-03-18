# Saki Controlplane DB Enum Normalization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `saki-controlplane` 中闭集型数据库字段从 `text/check` 统一收敛为 PostgreSQL `enum`，并同步整理迁移历史、`sqlc` 生成类型与 repo 适配层。

**Architecture:** 直接重写未发布的 migration 历史，令 `runtime/importing/access/asset` 的建表脚本即为最终态；对已分裂的历史迁移执行“前一版收敛为最终态，后一版改为 no-op”。`sqlc` 负责把数据库 `enum` 暴露为 Go 强类型，repo 边界负责在强类型与现有字符串上层接口之间做最小转换。

**Tech Stack:** Go, PostgreSQL, goose, sqlc, pgx/v5, testcontainers

---

## Chunk 1: Enum Schema And SQLC Contracts

### Task 1: Lock enum targets with failing generated-type tests

**Files:**
- Create: `saki-controlplane/internal/gen/sqlc/model_enum_types_test.go`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run `cd saki-controlplane && go test ./internal/gen/sqlc -run TestGeneratedEnumTypes -v` and verify failure**
- [ ] **Step 3: Use the failure output as the contract for schema/query updates**

### Task 2: Rewrite migrations into final enum-first schema

**Files:**
- Modify: `saki-controlplane/db/migrations/000030_runtime_tables.sql`
- Modify: `saki-controlplane/db/migrations/000031_runtime_core_alignment.sql`
- Modify: `saki-controlplane/db/migrations/000050_import_tables.sql`
- Modify: `saki-controlplane/db/migrations/000060_access_identity.sql`
- Modify: `saki-controlplane/db/migrations/000070_asset_tables.sql`
- Modify: `saki-controlplane/db/migrations/000071_asset_durable_upload.sql`

- [ ] **Step 1: Fold runtime final schema into `000030` and make `000031` a no-op**
- [ ] **Step 2: Introduce import/access enum types directly in their original migration files**
- [ ] **Step 3: Fold asset final schema into `000070` and make `000071` a no-op**
- [ ] **Step 4: Keep down migrations internally consistent with the rewritten history**

### Task 3: Update query typing so sqlc emits enum params/results

**Files:**
- Modify: `saki-controlplane/db/queries/runtime/task.sql`

- [ ] **Step 1: Replace enum-array text casts with enum-array casts where needed**
- [ ] **Step 2: Regenerate `sqlc` and confirm generated model/query param types now use enums**

## Chunk 2: Repo Adapters, Verification, And Commit

### Task 4: Adapt repo boundaries to generated enum types

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/repo/task_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/executor_repo.go`
- Modify: `saki-controlplane/internal/modules/importing/repo/task_repo.go`
- Modify: `saki-controlplane/internal/modules/importing/repo/upload_repo.go`
- Modify: `saki-controlplane/internal/modules/access/repo/principal_repo.go`

- [ ] **Step 1: Convert repo input params into generated enum types at the SQL boundary**
- [ ] **Step 2: Convert generated enum result fields back to existing string-facing structs where needed**
- [ ] **Step 3: Keep runtime/import/access upper layers behaviorally unchanged**

### Task 5: Full verification and commit

**Files:**
- Modify: generated files under `saki-controlplane/internal/gen/sqlc`

- [ ] **Step 1: Run targeted tests for generated types and affected repos**
- [ ] **Step 2: Run `cd saki-controlplane && go test ./...`**
- [ ] **Step 3: Review `git diff` for migration history consistency**
- [ ] **Step 4: Commit with a single normalization commit**
