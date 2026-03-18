# Saki Asset Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `saki-controlplane` 建立通用 asset 元数据与对象存储签名能力，并让 import upload 与 runtime artifact 基于同一套存储基础设施工作。

**Architecture:** 在 `saki-controlplane` 内新增 `asset` 模块承载物理对象元数据真相；新增 `internal/app/storage` 承载对象存储 provider；`importing` 保留 upload session 领域，但上传内容从本地文件直传切到对象存储 presign；runtime 的 `ArtifactService` 只负责发放 upload/download ticket，不承载额外业务真相。本轮明确不做 sample 级 `primary_asset_id/asset_group` 迁移，也不接入 GC。

**Tech Stack:** Go, MinIO (S3-compatible), connect-go, ogen, pgx/v5, sqlc, goose, testcontainers-go

---

**Execution Note:** 本计划按 `7042ba1` 之前的 clean HEAD 编写。若直接在当前 workspace 执行，需要先核对哪些步骤已经完成，并把对应任务从“红灯”改成“diff review + 增量测试”。

## Planned Files

- Create: `saki-controlplane/internal/app/storage/provider.go`
- Create: `saki-controlplane/internal/app/storage/minio.go`
- Create: `saki-controlplane/internal/app/storage/provider_test.go`
- Modify: `saki-controlplane/internal/app/config/config.go`
- Modify: `saki-controlplane/internal/app/config/config_test.go`
- Modify: `saki-controlplane/go.mod`
- Modify: `saki-controlplane/go.sum`
- Create: `saki-controlplane/db/migrations/000070_asset_tables.sql`
- Create: `saki-controlplane/db/queries/asset/asset.sql`
- Modify: `saki-controlplane/db/sqlc.yaml`
- Create: `saki-controlplane/internal/modules/asset/repo/asset_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/repo_test.go`
- Create: `saki-controlplane/internal/modules/asset/app/asset.go`
- Create: `saki-controlplane/internal/modules/asset/app/ticket.go`
- Create: `saki-controlplane/internal/modules/asset/app/asset_test.go`
- Create: `saki-controlplane/internal/modules/asset/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/asset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-controlplane/internal/modules/importing/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/importing/apihttp/sse.go`
- Modify: `saki-controlplane/internal/modules/importing/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations.go`
- Modify: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations_test.go`
- Modify: `saki-controlplane/internal/modules/importing/repo/upload_repo.go`
- Modify: `saki-controlplane/internal/modules/importing/repo/repo_test.go`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/artifact_server.go`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/artifact_server_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/runner.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`

## Chunk 1: Storage And Asset Truth

### Task 1: 加入对象存储配置与 MinIO provider

**Files:**
- Create: `saki-controlplane/internal/app/storage/provider.go`
- Create: `saki-controlplane/internal/app/storage/minio.go`
- Create: `saki-controlplane/internal/app/storage/provider_test.go`
- Modify: `saki-controlplane/internal/app/config/config.go`
- Modify: `saki-controlplane/internal/app/config/config_test.go`
- Modify: `saki-controlplane/go.mod`
- Modify: `saki-controlplane/go.sum`
- Test: `saki-controlplane/internal/app/config/config_test.go`
- Test: `saki-controlplane/internal/app/storage/provider_test.go`

- [ ] **Step 1: 写失败测试，锁定配置字段与 provider 能力边界**

```go
func TestLoadIncludesObjectStorageConfig(t *testing.T) {}
func TestMinioProviderSignsPutAndGetURL(t *testing.T) {}
func TestMinioProviderStatsAndDownloadsObject(t *testing.T) {}
```

配置字段至少包含：

```go
MinIOEndpoint   string `env:"MINIO_ENDPOINT"`
MinIOAccessKey  string `env:"MINIO_ACCESS_KEY"`
MinIOSecretKey  string `env:"MINIO_SECRET_KEY"`
MinIOBucketName string `env:"MINIO_BUCKET_NAME"`
MinIOSecure     bool   `env:"MINIO_SECURE" envDefault:"false"`
```

provider 接口最小集合：

```go
type Provider interface {
    Bucket() string
    SignPutObject(ctx context.Context, objectKey string, expiry time.Duration, contentType string) (string, error)
    SignGetObject(ctx context.Context, objectKey string, expiry time.Duration) (string, error)
    StatObject(ctx context.Context, objectKey string) (*ObjectStat, error)
    DownloadObject(ctx context.Context, objectKey string, dst string) error
}
```

- [ ] **Step 2: 运行配置/provider 测试，确认当前 controlplane 不具备对象存储能力**

Run: `cd saki-controlplane && go test ./internal/app/config ./internal/app/storage -run 'TestLoadIncludesObjectStorageConfig|TestMinioProvider' -v`
Expected: FAIL，原因是当前 `Config` 没有对象存储字段，`internal/app/storage` 尚不存在。

- [ ] **Step 3: 实现配置与 provider**

要求：

1. provider 放在 `internal/app/storage`，不要把对象存储细节塞进 `asset` / `importing` / `runtime` 模块。
2. MinIO 实现只暴露当前需要的方法：`SignPutObject`、`SignGetObject`、`StatObject`、`DownloadObject`。
3. 构造函数使用配置对象，而不是零散参数列表，避免 bootstrap 处参数蔓延。
4. 对外错误统一为 provider 层错误，不泄漏 MinIO SDK 细节。
5. 配置字段名称沿用仓库现有部署约定 `MINIO_*`，不要另起一套 `OBJECT_STORAGE_*`。

- [ ] **Step 4: 重新运行配置/provider 测试**

Run: `cd saki-controlplane && go test ./internal/app/config ./internal/app/storage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/app/config/config.go \
  saki-controlplane/internal/app/config/config_test.go \
  saki-controlplane/go.mod \
  saki-controlplane/go.sum \
  saki-controlplane/internal/app/storage/provider.go \
  saki-controlplane/internal/app/storage/minio.go \
  saki-controlplane/internal/app/storage/provider_test.go
git commit -m "feat(controlplane): add object storage provider foundation"
```

### Task 2: 建立 asset 元数据表、repo 与应用用例

**Files:**
- Create: `saki-controlplane/db/migrations/000070_asset_tables.sql`
- Create: `saki-controlplane/db/queries/asset/asset.sql`
- Modify: `saki-controlplane/db/sqlc.yaml`
- Create: `saki-controlplane/internal/modules/asset/repo/asset_repo.go`
- Create: `saki-controlplane/internal/modules/asset/repo/repo_test.go`
- Create: `saki-controlplane/internal/modules/asset/app/asset.go`
- Create: `saki-controlplane/internal/modules/asset/app/ticket.go`
- Create: `saki-controlplane/internal/modules/asset/app/asset_test.go`
- Test: `saki-controlplane/internal/modules/asset/repo/repo_test.go`
- Test: `saki-controlplane/internal/modules/asset/app/asset_test.go`

- [ ] **Step 1: 写失败测试，锁定 asset 真相与 ticket 语义**

```go
func TestAssetRepoCreatePendingAndMarkReady(t *testing.T) {}
func TestAssetRepoGetByStorageLocation(t *testing.T) {}
func TestIssueUploadTicketRequiresPendingAsset(t *testing.T) {}
func TestIssueDownloadTicketRequiresReadyAsset(t *testing.T) {}
```

asset 表最小字段：

```sql
id uuid primary key default gen_random_uuid(),
kind text not null,
status text not null,
storage_backend text not null,
bucket text not null,
object_key text not null,
content_type text not null default '',
size_bytes bigint not null default 0,
sha256_hex text,
metadata jsonb not null default '{}'::jsonb,
created_by uuid,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now(),
unique (bucket, object_key)
```

状态先只允许：

```go
const (
    AssetStatusPendingUpload = "pending_upload"
    AssetStatusReady         = "ready"
)
```

- [ ] **Step 2: 运行 repo/app 测试，确认当前没有 asset 模块**

Run: `cd saki-controlplane && go test ./internal/modules/asset/... -v`
Expected: FAIL，原因是 migration/query/module 尚不存在。

- [ ] **Step 3: 新增 asset migration、sqlc query、repo 与 app**

要求：

1. repo 只承载持久化操作：`CreatePending`、`Get`、`GetByStorageLocation`、`MarkReady`。
2. app 层负责 ticket 语义校验，不让 handler / rpc 直接操作 repo。
3. `IssueUploadTicket` 只能对 `pending_upload` asset 发 ticket。
4. `IssueDownloadTicket` 只能对 `ready` asset 发 ticket。
5. 这一轮不要加入 sample/project/dataset 关联表。

- [ ] **Step 4: 生成 sqlc 并跑 repo/app 测试**

Run: `cd saki-controlplane && make gen-sqlc && go test ./internal/modules/asset/... -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/db/migrations/000070_asset_tables.sql \
  saki-controlplane/db/queries/asset/asset.sql \
  saki-controlplane/db/sqlc.yaml \
  saki-controlplane/internal/modules/asset/repo/asset_repo.go \
  saki-controlplane/internal/modules/asset/repo/repo_test.go \
  saki-controlplane/internal/modules/asset/app/asset.go \
  saki-controlplane/internal/modules/asset/app/ticket.go \
  saki-controlplane/internal/modules/asset/app/asset_test.go \
  saki-controlplane/internal/gen/sqlc
git commit -m "feat(asset): add asset metadata store and ticket usecases"
```

## Chunk 2: Public API And Import Upload Integration

### Task 3: 暴露最小 asset Public API

**Files:**
- Create: `saki-controlplane/internal/modules/asset/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/asset/apihttp/handlers_test.go`
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Test: `saki-controlplane/internal/modules/asset/apihttp/handlers_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`

- [ ] **Step 1: 写失败测试，锁定 public API 的最小 asset 流程**

```go
func TestInitAssetUploadReturnsPendingAssetAndSignedPutURL(t *testing.T) {}
func TestCompleteAssetUploadMarksAssetReady(t *testing.T) {}
func TestGetAssetReturnsMetadata(t *testing.T) {}
func TestSignAssetDownloadReturnsSignedGetURL(t *testing.T) {}
```

OpenAPI 新增的最小接口：

```yaml
POST /assets/uploads:init
POST /assets/{asset_id}:complete
GET  /assets/{asset_id}
POST /assets/{asset_id}:sign-download
```

- [ ] **Step 2: 运行 asset API 测试，确认当前 public-api 没有 asset 入口**

Run: `cd saki-controlplane && go test ./internal/modules/asset/apihttp ./internal/modules/system/apihttp -run 'TestInitAssetUpload|TestCompleteAssetUpload|TestGetAsset|TestSignAssetDownload|TestPublicAPISmoke' -v`
Expected: FAIL，原因是 OpenAPI、handler、bootstrap wiring 尚未存在。

- [ ] **Step 3: 实现 asset API，并接入 system server / bootstrap**

要求：

1. `InitAssetUpload` 创建 `pending_upload` asset，并立即签发单文件 PUT URL。
2. `CompleteAssetUpload` 通过 provider `StatObject` 读取实际对象大小，再写回 asset record；如请求显式给出 `size_bytes` / `sha256_hex`，要校验或持久化。
3. `GetAsset` 只返回元数据，不返回下载 URL。
4. `SignAssetDownload` 只给 `ready` asset 发下载 ticket。
5. handler 不直接依赖 MinIO SDK，只依赖 app usecase。

- [ ] **Step 4: 生成 OpenAPI 并运行 API/烟测**

Run: `cd saki-controlplane && make gen-openapi && go test ./internal/modules/asset/apihttp ./internal/modules/system/apihttp -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/openapi/public-api.yaml \
  saki-controlplane/internal/modules/asset/apihttp/handlers.go \
  saki-controlplane/internal/modules/asset/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/system/apihttp/server.go \
  saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/app/bootstrap/bootstrap_test.go \
  saki-controlplane/internal/gen/openapi
git commit -m "feat(asset): expose asset upload and download public api"
```

### Task 4: 将 importing upload session 从本地落盘切到对象存储签名上传

**Files:**
- Modify: `saki-controlplane/internal/modules/importing/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/importing/apihttp/sse.go`
- Modify: `saki-controlplane/internal/modules/importing/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations.go`
- Modify: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations_test.go`
- Modify: `saki-controlplane/internal/modules/importing/repo/upload_repo.go`
- Modify: `saki-controlplane/internal/modules/importing/repo/repo_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`
- Test: `saki-controlplane/internal/modules/importing/apihttp/handlers_test.go`
- Test: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Test: `saki-controlplane/internal/app/bootstrap/bootstrap_test.go`

- [ ] **Step 1: 写失败测试，锁定 import upload 不再依赖本地文件路径**

```go
func TestInitImportUploadSessionReturnsSignedPutURL(t *testing.T) {}
func TestCompleteImportUploadSessionStatsRemoteObject(t *testing.T) {}
func TestPrepareProjectAnnotationsLoadsArchiveFromObjectStorage(t *testing.T) {}
```

- [ ] **Step 2: 运行 importing 测试，确认当前实现仍依赖 `uploadContentURL` 和 `os.Stat`**

Run: `cd saki-controlplane && go test ./internal/modules/importing/... ./internal/modules/system/apihttp -run 'TestInitImportUploadSession|TestCompleteImportUploadSession|TestPrepareProjectAnnotations|TestPublicAPISmoke' -v`
Expected: FAIL，原因是当前导入上传仍走 `PUT /imports/uploads/{id}/content` 本地文件路径。

- [ ] **Step 3: 先在 bootstrap 中注入可替换的 storage provider seam**

要求：

1. `bootstrap.NewPublicAPI` 能把 provider 显式传给 importing 相关依赖。
2. `bootstrap_test.go` 与 `openapi_smoke_test.go` 不强依赖真实 MinIO；优先引入 fake-provider seam，而不是在本任务里搭完整 MinIO fixture。
3. 这一步只处理 wiring，不改 importing handler 行为。

- [ ] **Step 4: 将 Init/Complete upload handler 改为 provider-backed presign/stat**

要求：

1. `InitImportUploadSession` 继续返回现有 openapi shape，但 `strategy=single_put` 时返回对象存储 presigned PUT URL，而不是本地 `/content`。
2. `SignImportUploadParts` 本轮仍可返回空 parts；但不能伪装 multipart 已完成。
3. `CompleteImportUploadSession` 用 provider `StatObject` 验证远端对象存在和大小，不再依赖 `os.Stat`。
4. 这一步只改 API handler，不改 prepare usecase。

- [ ] **Step 5: 让 PrepareProjectAnnotations 从 provider 下载对象，而不是直读本地 object_key**

要求：

1. `PrepareProjectAnnotations` 在需要解析压缩包时，通过 provider 下载到临时文件或读取远端对象，而不是直接打开本地 `object_key`。
2. `paramsHash` 与 preview manifest 不应再把“本地临时路径语义”当作稳定输入。

- [ ] **Step 6: 删除仅服务于本地文件上传的 `/content` 路由和文件系统写入**

要求：

1. `apihttp/sse.go` 必须同步收口或删除其 `/content` 路由分支。
2. 删除后 smoke test 不再依赖 `PUT /imports/uploads/{id}/content`。

- [ ] **Step 7: 重新运行 importing / bootstrap / smoke 测试**

Run: `cd saki-controlplane && go test ./internal/modules/importing/... ./internal/modules/system/apihttp ./internal/app/bootstrap -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/app/bootstrap/bootstrap_test.go \
  saki-controlplane/internal/modules/importing/apihttp/handlers.go \
  saki-controlplane/internal/modules/importing/apihttp/sse.go \
  saki-controlplane/internal/modules/importing/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/importing/app/prepare_project_annotations.go \
  saki-controlplane/internal/modules/importing/app/prepare_project_annotations_test.go \
  saki-controlplane/internal/modules/importing/repo/upload_repo.go \
  saki-controlplane/internal/modules/importing/repo/repo_test.go \
  saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go
git commit -m "feat(import): back upload sessions with object storage"
```

## Chunk 3: Runtime Artifact Tickets

### Task 5: 实现 runtime ArtifactService 并挂到 runtime role

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/artifact_server.go`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/artifact_server_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/runner.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/artifact_server_test.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go`
- Test: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`

- [ ] **Step 1: 写失败测试，锁定 ArtifactService 只发 ticket 的职责**

```go
func TestArtifactServerCreateUploadTicketForPendingAsset(t *testing.T) {}
func TestArtifactServerRejectsUploadTicketForReadyAsset(t *testing.T) {}
func TestArtifactServerCreateDownloadTicketForReadyAsset(t *testing.T) {}
```

- [ ] **Step 2: 运行 runtime internalrpc 测试，确认当前只有 AgentIngress，没有 ArtifactService handler**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/internalrpc -run 'TestArtifactServer|TestRuntimeServer' -v`
Expected: FAIL，原因是 runtime role 未挂载 `ArtifactService`。

- [ ] **Step 3: 新增 artifact rpc server，仅实现 ticket 语义**

要求：

1. 新文件 `artifact_server.go` 单独承载 `ArtifactService`，不要把逻辑塞进现有 `runtime_server.go`。
2. `CreateUploadTicket` 复用 asset app 的 `IssueUploadTicket`。
3. `CreateDownloadTicket` 复用 asset app 的 `IssueDownloadTicket`。
4. 这一步只新增 server 与 server test，不改 runner。
5. runtime 只发 ticket，不创建 asset record。

- [ ] **Step 4: 修改 runner 为双 handler 装配，并补 runner/contract 测试**

要求：

1. `runner.go` 同时挂 `AgentIngress` 与 `ArtifactService` 两个 Connect handler。
2. `runner_test.go` 需要覆盖 multi-handler wiring，而不是只测单 ingress。
3. `runtime_contract_test.go` 增加 `ArtifactService` 的 descriptor/codec 断言，避免只测实现不测合同。

- [ ] **Step 5: 生成 proto 并运行 runtime internalrpc / runner 测试**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc ./internal/modules/runtime/app/runtime -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/internalrpc/artifact_server.go \
  saki-controlplane/internal/modules/runtime/internalrpc/artifact_server_test.go \
  saki-controlplane/internal/modules/runtime/app/runtime/runner.go \
  saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go
git commit -m "feat(runtime): expose artifact ticket service"
```

## Final Verification

- [ ] **Step 1: 运行完整生成检查**

Run: `cd saki-controlplane && make gen`
Expected: PASS，且 `internal/gen/openapi`、`internal/gen/proto`、`internal/gen/sqlc` 与源码一致。

- [ ] **Step 2: 运行重点测试集**

Run: `cd saki-controlplane && go test ./internal/app/config ./internal/app/storage ./internal/modules/asset/... ./internal/modules/importing/... ./internal/modules/runtime/internalrpc ./internal/modules/system/apihttp -v`
Expected: PASS

- [ ] **Step 3: 运行公开 API smoke test**

Run: `cd saki-controlplane && make smoke-public-api`
Expected: PASS

- [ ] **Step 4: 运行 runtime 相关测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/... -v`
Expected: PASS

- [ ] **Step 5: 最终提交**

```bash
git add docs/superpowers/plans/2026-03-18-saki-asset-foundation.md
git commit -m "docs: add asset foundation implementation plan"
```
