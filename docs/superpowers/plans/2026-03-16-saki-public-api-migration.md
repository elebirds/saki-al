# Saki Public API Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 `ogen` 建立新的 `public-api role`，并迁移第一批核心模块：`system/access/project/runtime-admin`，为后续 annotation/import API 迁移铺路。

**Architecture:** 采用 OpenAPI-first。先实现统一错误模型、鉴权中间件和健康检查，再迁移 system/access/project/runtime-admin 四组接口。剩余 annotation/import/export 在此基础上继续增量迁移。

**Tech Stack:** Go, `ogen`, `net/http`, `slog`, `pgx/v5`, `sqlc`

---

## Chunk 1: API Framework, Error Model, And Auth

### Task 1: Build the `ogen` public API skeleton

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Create: `saki-controlplane/internal/modules/system/apihttp/errors.go`
- Modify: `saki-controlplane/cmd/public-api/main.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/server_test.go`

- [ ] **Step 1: Write failing tests for `/healthz` and structured error responses**
- [ ] **Step 2: Run `cd saki-controlplane && make gen-openapi && go test ./internal/modules/system/apihttp -v` and verify failure**
- [ ] **Step 3: Expand `public-api.yaml` with health and error schema**
- [ ] **Step 4: Implement generated server wiring and shared error mapping**
- [ ] **Step 5: Re-run tests and commit**

```bash
git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/system/apihttp saki-controlplane/cmd/public-api/main.go
git commit -m "feat(public-api): add ogen server skeleton"
```

### Task 2: Add auth and permission middleware

**Files:**
- Create: `saki-controlplane/internal/app/auth/middleware.go`
- Create: `saki-controlplane/internal/modules/access/app/authenticate.go`
- Create: `saki-controlplane/internal/modules/access/apihttp/handlers.go`
- Test: `saki-controlplane/internal/modules/access/apihttp/handlers_test.go`

- [ ] **Step 1: Write failing tests for login/current-user/permission denial behavior**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Implement token parsing, current-user context injection, and permission checks**
- [ ] **Step 4: Wire generated access handlers to app layer and make tests pass**
- [ ] **Step 5: Commit**

## Chunk 2: First Migrated Modules

### Task 3: Migrate project APIs

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/project/app/create_project.go`
- Create: `saki-controlplane/internal/modules/project/app/list_projects.go`
- Create: `saki-controlplane/internal/modules/project/app/get_project.go`
- Create: `saki-controlplane/internal/modules/project/apihttp/handlers.go`
- Test: `saki-controlplane/internal/modules/project/apihttp/handlers_test.go`

- [ ] **Step 1: Write failing tests for create/list/get project endpoints**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Add OpenAPI schemas and routes for the first project endpoints**
- [ ] **Step 4: Implement app use cases and handlers backed by `project/repo`**
- [ ] **Step 5: Run tests and commit**

```bash
git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/project/app saki-controlplane/internal/modules/project/apihttp
git commit -m "feat(public-api): migrate project endpoints"
```

### Task 4: Expose runtime admin read and command endpoints

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/runtime/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/runtime/app/queries/get_runtime_summary.go`
- Create: `saki-controlplane/internal/modules/runtime/app/queries/list_executors.go`
- Create: `saki-controlplane/internal/modules/runtime/app/queries/issue_runtime_command.go`
- Test: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`

- [ ] **Step 1: Write failing tests for runtime summary, executors list, loop/task command endpoints**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Add OpenAPI operations for runtime admin queries and command endpoints**
- [ ] **Step 4: Wire handlers to runtime app layer commands/queries**
- [ ] **Step 5: Re-run tests and commit**

### Task 5: Add API generation drift and smoke checks

**Files:**
- Modify: `saki-controlplane/Makefile`
- Modify: `saki-controlplane/.github/workflows/controlplane-ci.yml`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`

- [ ] **Step 1: Add a failing smoke test that starts the public API and probes generated routes**
- [ ] **Step 2: Run smoke test and verify failure**
- [ ] **Step 3: Add CI checks for `make gen-openapi` drift and public API smoke tests**
- [ ] **Step 4: Run `cd saki-controlplane && go test ./internal/modules/.../apihttp -v` and make it pass**
- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/Makefile saki-controlplane/.github/workflows/controlplane-ci.yml
git commit -m "chore(public-api): add api drift and smoke checks"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-16-saki-public-api-migration.md`. Ready to execute?
