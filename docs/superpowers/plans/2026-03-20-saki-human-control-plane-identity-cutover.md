# Saki Human Control Plane Identity Cutover Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `saki-controlplane` 中落地本地优先的人类控制面身份/会话/授权体系，完成 `system / init / auth / user / rbac / members` 从旧 `saki-api` 到 Go controlplane 的主迁移闭环。

**Architecture:** 先建立新的 `identity / authorization / system` 存储与应用边界，再打通 `setup + auth + system-status/settings` 的最小闭环，随后补齐 `users / roles / permissions / members`，最后切换前端启动链并兼容旧密码哈希数据。现有 `access` 模块只保留为迁移期的认证中间件外壳，核心人类控制面能力逐步迁入新模块。

**Tech Stack:** Go, OpenAPI/ogen, pgx/sqlc, goose, React/TypeScript, Argon2id, HMAC/JWT access token, 数据库存储 refresh session

---

## File Map

### 新增模块与文件

- Create: `saki-controlplane/internal/modules/identity/domain/*.go`
- Create: `saki-controlplane/internal/modules/identity/app/*.go`
- Create: `saki-controlplane/internal/modules/identity/repo/*.go`
- Create: `saki-controlplane/internal/modules/identity/apihttp/*.go`
- Create: `saki-controlplane/internal/modules/authorization/domain/*.go`
- Create: `saki-controlplane/internal/modules/authorization/app/*.go`
- Create: `saki-controlplane/internal/modules/authorization/repo/*.go`
- Create: `saki-controlplane/internal/modules/authorization/apihttp/*.go`
- Create: `saki-controlplane/internal/modules/system/app/*.go`
- Create: `saki-controlplane/internal/modules/system/repo/*.go`
- Create: `saki-controlplane/internal/modules/system/domain/*.go`
- Create: `saki-controlplane/db/queries/identity/*.sql`
- Create: `saki-controlplane/db/queries/authorization/*.sql`
- Create: `saki-controlplane/db/queries/system/*.sql`
- Create: `saki-controlplane/db/migrations/000080_human_control_plane_identity.sql`
- Create: `saki-controlplane/db/migrations/000090_human_control_plane_authorization.sql`
- Create: `saki-controlplane/db/migrations/000100_human_control_plane_system.sql`
- Create: `saki-controlplane/internal/modules/identity/*_test.go`
- Create: `saki-controlplane/internal/modules/authorization/*_test.go`
- Create: `saki-controlplane/internal/modules/system/*_test.go`
- Create: `saki-controlplane/internal/modules/system/apihttp/human_controlplane_smoke_test.go`

### 必改文件

- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/db/sqlc.yaml`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server_test.go`
- Modify: `saki-controlplane/internal/modules/access/app/authenticate.go`
- Modify: `saki-controlplane/internal/modules/access/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/access/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-web/src/services/api/interface.ts`
- Modify: `saki-web/src/services/api/real.ts`
- Modify: `saki-web/src/store/systemStore.ts`
- Modify: `saki-web/src/components/ProtectedLayout.tsx`
- Modify: `saki-web/src/components/SystemCheck.tsx`
- Modify: `saki-web/src/pages/base/Setup.tsx`
- Modify: `saki-web/src/pages/user/Login.tsx`
- Modify: `saki-web/src/pages/user/Register.tsx`
- Modify: `saki-web/src/pages/user/ChangePassword.tsx`
- Modify: `saki-web/src/pages/user/UserManagement.tsx`
- Modify: `saki-web/src/pages/user/RoleManagement.tsx`
- Modify: `saki-web/src/pages/system/SystemSettings.tsx`
- Modify: `saki-web/src/components/settings/DatasetMembers.tsx`
- Modify: `saki-web/src/pages/project/ProjectSettings.tsx`

### 迁移期兼容约束

- 旧密码哈希数据需要兼容登录，但前端协议不再发送 SHA-256 结果。
- 旧 refresh token 不兼容，新 controlplane 接管后统一要求重新登录。
- 关键设计必须写入中文注释，尤其是：
  - 为什么 `identity / authorization / system` 分层
  - 为什么 refresh session 必须落库
  - 为什么兼容旧密码哈希只在服务端验证分支保留

### 明确非目标与硬约束

- 第一阶段只实现 `local_password` 凭据提供方，不提前抽象可插拔 OAuth/OIDC provider 框架。
- 第一阶段不引入独立 FGA/ReBAC 系统，资源授权继续采用代码定义权限目录 + 内建资源角色。
- permission catalog 由代码定义，不做数据库可运营化配置。
- `access_token` 默认 TTL 固定为 10 分钟，`refresh_session` 默认 TTL 固定为 30 天；测试必须断言这两个默认值。
- `GET /system/status` 必须返回 `install_state`、`allow_self_register`、`version` 三个字段；测试必须断言字段齐全和来源正确。
- 前端在 `401` 或 refresh 失败时必须清理本地 token、当前用户缓存和相关 boot 状态，再统一跳回登录页。

## Chunk 1: Storage And Domain Foundation

### Task 1: 建立 identity/authorization/system 的数据库骨架与生成代码

**Files:**
- Create: `saki-controlplane/db/migrations/000080_human_control_plane_identity.sql`
- Create: `saki-controlplane/db/migrations/000090_human_control_plane_authorization.sql`
- Create: `saki-controlplane/db/migrations/000100_human_control_plane_system.sql`
- Create: `saki-controlplane/db/queries/identity/principal.sql`
- Create: `saki-controlplane/db/queries/identity/user.sql`
- Create: `saki-controlplane/db/queries/identity/credential.sql`
- Create: `saki-controlplane/db/queries/identity/session.sql`
- Create: `saki-controlplane/db/queries/authorization/role.sql`
- Create: `saki-controlplane/db/queries/authorization/binding.sql`
- Create: `saki-controlplane/db/queries/authorization/membership.sql`
- Create: `saki-controlplane/db/queries/system/installation.sql`
- Create: `saki-controlplane/db/queries/system/setting.sql`
- Modify: `saki-controlplane/db/sqlc.yaml`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`

- [ ] **Step 1: 写数据库迁移和 SQL 查询的失败期 smoke 断言**

  在 `openapi_smoke_test.go` 增加针对新路径的占位断言，并在后续任务逐步填实；同时新增针对 sqlc 生成符号的编译期引用测试，确保 query 命名稳定。

- [ ] **Step 2: 运行生成与相关 smoke 测试，确认当前失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && make gen && go test ./internal/modules/system/apihttp -run 'TestPublicAPISmoke|TestHumanControlPlane.*' -v`
  Expected: FAIL，提示缺少 schema/path/生成代码。

- [ ] **Step 3: 写最小 schema/migration/query**

  关键表：
  - `iam_principal`
  - `iam_user`
  - `iam_password_credential`
  - `iam_refresh_session`
  - `authz_role`
  - `authz_role_permission`
  - `authz_system_binding`
  - `authz_resource_membership`
  - `system_installation`
  - `system_setting`

  关键约束：
  - refresh session 存 `token_hash`，不存明文 token
  - credential 带 `scheme`
  - 安装态单例可被显式读取

- [ ] **Step 4: 重新生成代码并确认 smoke/编译通过**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && make gen && go test ./internal/modules/system/apihttp -run 'TestPublicAPISmoke|TestHumanControlPlane.*' -v`
  Expected: PASS 或进入下一任务前仅保留 handler 未实现失败。

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/db saki-controlplane/internal/gen
  git commit -m "feat(identity): add human control plane schema foundation"
  ```

### Task 2: 建立 identity/authorization/system 的 repo/app/domain 骨架

**Files:**
- Create: `saki-controlplane/internal/modules/identity/domain/principal.go`
- Create: `saki-controlplane/internal/modules/identity/domain/user.go`
- Create: `saki-controlplane/internal/modules/identity/domain/credential.go`
- Create: `saki-controlplane/internal/modules/identity/domain/session.go`
- Create: `saki-controlplane/internal/modules/identity/app/password_hasher.go`
- Create: `saki-controlplane/internal/modules/identity/app/token_issuer.go`
- Create: `saki-controlplane/internal/modules/identity/app/credential_verifier.go`
- Create: `saki-controlplane/internal/modules/identity/repo/*.go`
- Create: `saki-controlplane/internal/modules/authorization/domain/*.go`
- Create: `saki-controlplane/internal/modules/authorization/app/*.go`
- Create: `saki-controlplane/internal/modules/authorization/repo/*.go`
- Create: `saki-controlplane/internal/modules/system/domain/*.go`
- Create: `saki-controlplane/internal/modules/system/app/*.go`
- Create: `saki-controlplane/internal/modules/system/repo/*.go`
- Test: `saki-controlplane/internal/modules/identity/app/credential_verifier_test.go`
- Test: `saki-controlplane/internal/modules/identity/app/session_service_test.go`
- Test: `saki-controlplane/internal/modules/authorization/app/authorizer_test.go`
- Test: `saki-controlplane/internal/modules/system/app/settings_service_test.go`

- [ ] **Step 1: 写 domain/app 层失败测试**

  覆盖：
  - 新旧密码 scheme 验证
  - refresh session rotation
  - authorizer 的系统角色与资源成员解析

- [ ] **Step 2: 运行 identity/access 相关测试，确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/... ./internal/modules/authorization/... ./internal/modules/system/... -v`
  Expected: FAIL，提示缺少新 store/usecase。

- [ ] **Step 3: 实现最小骨架**

  关键实现要求：
  - `credential_verifier` 同时支持 `password_argon2id` 和 `legacy_frontend_sha256_argon2`
  - `credential_verifier` 明确只支持 `local_password` 语义，不预埋外部 provider 框架
  - `authorizer` 统一封装系统角色与资源成员解析
  - 在代码中用中文注释说明：权限目录由代码定义是为了保持稳定、可测试、可审计

- [ ] **Step 4: 跑模块测试确认骨架稳定**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/... ./internal/modules/authorization/... ./internal/modules/system/... -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/internal/modules/identity saki-controlplane/internal/modules/authorization saki-controlplane/internal/modules/system
  git commit -m "feat(identity): add domain and repository skeleton"
  ```

### Task 3: 接入 access middleware 聚合装载与迁移期兼容壳

**Files:**
- Modify: `saki-controlplane/internal/modules/access/app/store.go`
- Modify: `saki-controlplane/internal/modules/access/app/authenticate.go`
- Modify: `saki-controlplane/internal/modules/access/app/authenticate_test.go`
- Modify: `saki-controlplane/internal/modules/access/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/access/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Test: `saki-controlplane/internal/modules/access/app/authenticate_test.go`
- Test: `saki-controlplane/internal/modules/access/apihttp/handlers_test.go`

- [ ] **Step 1: 为 access 聚合装载写失败测试**

  覆盖：
  - `IssueTokenContext` 从 identity/authorization 聚合 store 装载 claims
  - claims 权限快照来自 authorizer，而不是 handler 自行拼装
  - 迁移期 `access` 模块只承担 HTTP auth 壳职责

- [ ] **Step 2: 运行 access 测试确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/access/... -v`
  Expected: FAIL

- [ ] **Step 3: 实现最小聚合接线**

  关键实现要求：
  - `access.Authenticator` 改为通过 identity/authorization 聚合 store 取 principal 与 permission snapshot
  - 在代码中用中文注释说明：`access` 是迁移期 HTTP auth 外壳，正式人类控制面能力已迁入 `identity/authorization`

- [ ] **Step 4: 跑 access 测试**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/access/... -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/internal/modules/access saki-controlplane/internal/app/bootstrap/bootstrap.go
  git commit -m "refactor(access): wire auth shell to identity services"
  ```

## Chunk 2: Init + Auth + System Minimal Closure

### Task 4: 打通 `system/status + system/setup + system/types + system/settings`

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Create: `saki-controlplane/internal/modules/system/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/system/apihttp/handlers_test.go`
- Create: `saki-controlplane/internal/modules/system/app/get_status.go`
- Create: `saki-controlplane/internal/modules/system/app/setup.go`
- Create: `saki-controlplane/internal/modules/system/app/settings.go`
- Create: `saki-controlplane/internal/modules/system/app/status_test.go`
- Create: `saki-controlplane/internal/modules/system/app/setup_test.go`
- Create: `saki-controlplane/internal/modules/system/app/settings_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/human_controlplane_smoke_test.go`

- [ ] **Step 1: 为 system endpoints 写失败的 contract tests**

  覆盖：
  - 未初始化时 `GET /system/status`
  - `POST /system/setup`
  - `GET /system/types`
  - `GET /system/settings`
  - `PATCH /system/settings`
  - `GET /system/status` 明确断言 `install_state`、`allow_self_register`、`version`

- [ ] **Step 2: 运行 system/api smoke 测试确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/system/apihttp -run 'TestHumanControlPlaneSystem|TestPublicAPISmoke' -v`
  Expected: FAIL

- [ ] **Step 3: 实现最小 handler/usecase/wiring**

  关键语义：
  - `setup` 成功即返回首个管理员 session 对
  - `status` 返回 `install_state + allow_self_register + version`，且 `allow_self_register` 来源于 settings，`install_state` 来源于 installation 记录
  - settings 返回 `schema + values`
  - 关键事务边界和安装态语义写中文注释

- [ ] **Step 4: 运行 system/api 测试确认通过**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/system/apihttp -run 'TestHumanControlPlaneSystem|TestPublicAPISmoke' -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/app/bootstrap/bootstrap.go saki-controlplane/internal/modules/system saki-controlplane/internal/gen/openapi
  git commit -m "feat(system): add setup status and settings APIs"
  ```

### Task 5: 打通 `auth/login + refresh + logout + me + register + change-password`

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/identity/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/identity/apihttp/handlers_test.go`
- Create: `saki-controlplane/internal/modules/identity/app/login.go`
- Create: `saki-controlplane/internal/modules/identity/app/refresh.go`
- Create: `saki-controlplane/internal/modules/identity/app/logout.go`
- Create: `saki-controlplane/internal/modules/identity/app/register.go`
- Create: `saki-controlplane/internal/modules/identity/app/change_password.go`
- Create: `saki-controlplane/internal/modules/identity/app/login_test.go`
- Create: `saki-controlplane/internal/modules/identity/app/refresh_test.go`
- Create: `saki-controlplane/internal/modules/identity/app/change_password_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/access/apihttp/handlers.go`
- Test: `saki-controlplane/internal/modules/identity/apihttp/handlers_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/human_controlplane_smoke_test.go`

- [ ] **Step 1: 为 auth 闭环写失败测试**

  覆盖：
  - 新用户登录
  - refresh rotation
  - logout 撤销当前 session
  - `auth/me` 返回用户资料与权限
  - register 在开关关闭/开启两种状态下的行为
  - change-password 自动撤销旧 refresh family
  - 旧密码哈希用户登录后自动升级 `scheme`
  - `access_token` 默认 TTL 为 10 分钟
  - `refresh_session` 默认过期时间为 30 天

- [ ] **Step 2: 运行 identity/system smoke 测试确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/... ./internal/modules/system/apihttp -run 'TestHumanControlPlaneAuth|TestHumanControlPlaneSystem|TestPublicAPISmoke' -v`
  Expected: FAIL

- [ ] **Step 3: 实现最小 auth/session 逻辑**

  关键语义：
  - access token 默认 TTL 固定为 10 分钟，并在测试中断言
  - refresh token 随机串 + hash 落库，refresh session 默认 TTL 固定为 30 天，并在测试中断言
  - replay 检测直接撤销 family
  - 旧 refresh token 不兼容
  - 中文注释解释为什么 refresh session 必须落库

- [ ] **Step 4: 跑 identity/system 测试**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/... ./internal/modules/system/apihttp -run 'TestHumanControlPlaneAuth|TestHumanControlPlaneSystem|TestPublicAPISmoke' -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/identity saki-controlplane/internal/modules/access saki-controlplane/internal/modules/system saki-controlplane/internal/gen/openapi
  git commit -m "feat(identity): add auth session APIs"
  ```

## Chunk 3: Users + Roles + Permissions + Members

### Task 6: 完成 users 与 system roles 管理面

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/identity/app/user_admin.go`
- Create: `saki-controlplane/internal/modules/identity/apihttp/user_handlers.go`
- Create: `saki-controlplane/internal/modules/authorization/app/role_admin.go`
- Create: `saki-controlplane/internal/modules/authorization/apihttp/role_handlers.go`
- Create: `saki-controlplane/internal/modules/authorization/apihttp/permission_handlers.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Test: `saki-controlplane/internal/modules/identity/apihttp/user_handlers_test.go`
- Test: `saki-controlplane/internal/modules/authorization/apihttp/role_handlers_test.go`

- [ ] **Step 1: 为 users/roles/permissions 写失败测试**

  覆盖：
  - 用户分页、创建、禁用、软删除
  - 内建角色不可删改 key
  - 自定义角色 CRUD
  - `permissions/system`
  - `permissions/resource`
  - 禁用用户立即撤销 refresh sessions

- [ ] **Step 2: 运行相关 API 测试确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/apihttp ./internal/modules/authorization/apihttp -v`
  Expected: FAIL

- [ ] **Step 3: 实现最小 user/role/usecase/handler**

  关键语义：
  - 管理员创建用户默认 `must_change_password = true`
  - 删除用户采用软删除
  - 权限目录由代码定义，数据库只存角色映射
  - 中文注释解释“为什么 permission catalog 不做数据库动态配置”

- [ ] **Step 4: 跑 API 测试**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/apihttp ./internal/modules/authorization/apihttp -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/identity saki-controlplane/internal/modules/authorization saki-controlplane/internal/modules/system/apihttp/server.go saki-controlplane/internal/gen/openapi
  git commit -m "feat(authz): add users and system role management APIs"
  ```

### Task 7: 完成 project/dataset 成员管理与授权收口

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/authorization/app/member_admin.go`
- Create: `saki-controlplane/internal/modules/authorization/apihttp/member_handlers.go`
- Create: `saki-controlplane/internal/modules/authorization/app/member_authorizer_test.go`
- Modify: `saki-controlplane/internal/modules/project/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/dataset/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Test: `saki-controlplane/internal/modules/authorization/apihttp/member_handlers_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/human_controlplane_smoke_test.go`

- [ ] **Step 1: 为 project/dataset members 写失败测试**

  覆盖：
  - list/set/delete member
  - resource role catalog 返回
  - `internal/modules/authorization/app/member_authorizer_test.go` 断言成员写接口必须经由统一 authorizer，而不是 handler 直接查表

- [ ] **Step 2: 运行相关测试确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/authorization/apihttp ./internal/modules/system/apihttp -run 'Test.*Members|TestPublicAPISmoke' -v`
  Expected: FAIL

- [ ] **Step 3: 实现成员 API 与授权收口**

  关键语义：
  - 成员关系只支持内建资源角色
  - project/dataset 侧不新增可编程角色
  - 中文注释解释“为什么当前不引入 FGA/ReBAC”

- [ ] **Step 4: 运行授权与 smoke 测试**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/authorization/... ./internal/modules/system/apihttp -run 'Test.*Members|TestPublicAPISmoke' -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/authorization saki-controlplane/internal/modules/project saki-controlplane/internal/modules/dataset saki-controlplane/internal/modules/system/apihttp saki-controlplane/internal/gen/openapi
  git commit -m "feat(authz): add resource membership APIs"
  ```

## Chunk 4: Frontend Cutover And Data Compatibility

### Task 8: 切换前端 boot flow 与 auth/system pages 到新 public API

**Files:**
- Modify: `saki-web/src/services/api/interface.ts`
- Modify: `saki-web/src/services/api/real.ts`
- Modify: `saki-web/src/store/systemStore.ts`
- Modify: `saki-web/src/components/ProtectedLayout.tsx`
- Modify: `saki-web/src/components/SystemCheck.tsx`
- Modify: `saki-web/src/pages/base/Setup.tsx`
- Modify: `saki-web/src/pages/user/Login.tsx`
- Modify: `saki-web/src/pages/user/Register.tsx`
- Modify: `saki-web/src/pages/user/ChangePassword.tsx`
- Modify: `saki-web/src/pages/system/SystemSettings.tsx`
- Modify: `saki-web/src/store/authStore.ts`
- Test: `saki-web/src/components/ProtectedLayout.test.tsx`
- Test: `saki-web/src/components/SystemCheck.test.tsx`
- Test: `saki-web/src/pages/user/Login.test.tsx`
- Test: `saki-controlplane/internal/modules/system/apihttp/human_controlplane_smoke_test.go`

- [ ] **Step 1: 为前端 boot flow 改动列出失败场景并补必要测试**

  至少覆盖：
  - 未初始化进入 setup
  - refresh 失败清理 token/user cache/boot 状态后回登录
  - 任意 `401` 响应触发相同的状态清理策略
  - `must_change_password` 强制跳转
  - settings 页面读取/提交

- [ ] **Step 2: 运行前端现有 lint/test 或最小 smoke 校验**

  Run: `cd /Users/hhm/code/saki/saki-web && pnpm test -- --runInBand`
  Expected: FAIL 或暴露旧 API path 依赖。

- [ ] **Step 3: 切换 API client 与页面逻辑**

  关键语义：
  - 登录/注册/setup/改密不再先做前端 SHA-256
  - 新 `system/status` 决定启动链
  - refresh 调用 `/auth/refresh`
  - settings 统一走 `/system/settings`
  - refresh 失败或 `401` 时必须清理本地 token、当前用户缓存和 boot 状态，再统一跳回登录页

- [ ] **Step 4: 运行前端最小验证**

  Run: `cd /Users/hhm/code/saki/saki-web && pnpm test -- --runInBand`
  Expected: PASS；若仓库无稳定前端测试，至少执行 `pnpm lint` 并记录结果。

- [ ] **Step 5: Commit**

  ```bash
  git add saki-web/src
  git commit -m "feat(web): cut over boot flow to controlplane identity APIs"
  ```

### Task 9: 迁移旧数据并验证 legacy credential 升级

**Files:**
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Create: `saki-controlplane/internal/modules/identity/app/legacy_migration_test.go`
- Create: `saki-controlplane/internal/modules/identity/repo/legacy_import.go`
- Create: `saki-controlplane/internal/modules/identity/repo/legacy_import_test.go`
- Test: `saki-controlplane/internal/modules/identity/app/legacy_migration_test.go`

- [ ] **Step 1: 写旧数据兼容的失败测试**

  覆盖：
  - 旧 `Argon2(SHA256(password))` 用户可登录
  - 登录成功后凭据自动升级为 `password_argon2id`
  - 旧 refresh token 不兼容并返回明确错误

- [ ] **Step 2: 运行 legacy 兼容测试确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/... -run 'TestLegacy.*|TestLogin.*' -v`
  Expected: FAIL

- [ ] **Step 3: 实现最小旧数据兼容**

  关键语义：
  - 服务端保留旧密码 scheme 验证分支
  - 兼容的是旧数据库内的密码哈希，不是旧前端登录协议
  - 中文注释解释兼容边界

- [ ] **Step 4: 运行 legacy 测试**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && go test ./internal/modules/identity/... -run 'TestLegacy.*|TestLogin.*' -v`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane/internal/app/bootstrap/bootstrap.go saki-controlplane/internal/modules/identity
  git commit -m "feat(identity): support legacy password credential migration"
  ```

### Task 10: 清理 legacy auth surface 并做最终回归

**Files:**
- Modify: `saki-controlplane/internal/modules/access/*`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/legacy_runtime_api_cleanup_test.go`
- Test: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- [ ] **Step 1: 写 legacy API surface cleanup 的失败测试**

  覆盖：
  - public API 不再暴露旧伪 OAuth path

- [ ] **Step 2: 运行最终回归集合确认失败**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && make test-access && go test ./internal/modules/identity/... ./internal/modules/system/apihttp -v`
  Expected: FAIL

- [ ] **Step 3: 实现 legacy surface 清理**

  关键语义：
  - 删除或 404 掉旧 `/auth/login/access-token`、`/auth/login/refresh-token`
  - 保留足够中文注释解释为什么新协议不再兼容旧伪 OAuth surface

- [ ] **Step 4: 跑最终验证**

  Run: `cd /Users/hhm/code/saki/saki-controlplane && make gen && make test`
  Expected: PASS

  Run: `cd /Users/hhm/code/saki/saki-controlplane && make smoke-public-api`
  Expected: PASS

  Run: `cd /Users/hhm/code/saki/saki-web && pnpm lint`
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add saki-controlplane saki-web
  git commit -m "cleanup(identity): remove legacy auth surface and verify migration"
  ```

## Execution Notes

- 每个任务必须先写失败测试，再写最小实现，再跑测试，再提交。
- 每个任务完成后都要做两轮 subagent review：
  - 先做 spec compliance review
  - 再做 code quality review
- 任何 reviewer 提出的问题都必须修复并重新 review，不能跳过。
- 如果某个任务发现计划本身与实际代码结构冲突，先修计划文档并提交，再继续实现。

## Recommended Execution Order

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7
8. Task 8
9. Task 9
10. Task 10

Plan complete and saved to `docs/superpowers/plans/2026-03-20-saki-human-control-plane-identity-cutover.md`. Ready to execute.
