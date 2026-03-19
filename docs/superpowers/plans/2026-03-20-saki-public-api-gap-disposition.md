# Saki Public API 迁移处置清单

> 截止 2026-03-20。本清单只处理 `saki-api -> saki-controlplane public API` 的业务/API 处置，不覆盖 `dispatcher` 内部角色编排，也不覆盖 `agent` 宿主能力。

## 判断口径

- `必须迁移 / 先移除入口`：当前 `saki-web`、登录流程或现有操作路径仍直接依赖；在不改前端/入口的前提下，旧 API 不能下线。
- `可废弃`：当前未发现 `saki-web / scripts / docs` 依赖，或者新主线已经明确宣布旧 alias 结束生命周期。
- `待产品 / 架构确认`：是否保留取决于新的认证模型、运维模型或产品范围，不能仅凭“旧代码还在”直接判定。

## 结论

- 当前**不能**认定 `saki-api` 已完成 public API 迁移。
- 缺口不只在 `branch / commit / draft / export / model`，还包括 `auth/system`、`RBAC/member`、`sample read model`、`loop/prediction/plugin`、`import` 收口。
- `runtime/executors` 这类旧名词**不建议** 1:1 迁回；如果需要保留观测页，应直接改成新的 `agent` 语义和新页面。

## 一、必须迁移或先移除当前外部入口

| 能力 | 旧来源 | 当前依赖证据 | 当前 controlplane 状态 | 建议处置 |
| --- | --- | --- | --- | --- |
| 登录启动链与系统元信息 | `saki-api/src/saki_api/modules/access/api/http/auth.py`、`saki-api/src/saki_api/modules/system/api/http/system.py` | `saki-web/src/components/ProtectedLayout.tsx` 依赖 refresh token；`saki-web/src/components/SystemCheck.tsx`、`saki-web/src/pages/user/Login.tsx`、`saki-web/src/store/systemStore.ts` 依赖 `system/status`、`system/types` | `public-api.yaml` 只有 `/auth/login`、`/auth/me`、`/auth/permissions/{permission}`，没有 `system/status`、`system/types`、`refresh-token` | 若继续使用当前这套登录后自检与会话续签流程，就必须迁；若改成新的认证入口，就必须先统一前端 boot flow，再退役旧 API |
| RBAC、用户/角色、资源成员管理 | `saki-api/src/saki_api/modules/access/api/http/users.py`、`roles.py`、`permissions.py`、`saki-api/src/saki_api/modules/project/api/http/project.py` | `saki-web/src/App.tsx` 暴露 `/users`、`/roles`、`/projects/:projectId/members`；`saki-web/src/pages/user/UserManagement.tsx`、`RoleManagement.tsx`、`ProjectSettings.tsx`、`components/settings/DatasetMembers.tsx`、`hooks/permission/usePermission.ts` 直接调用 | 当前 public API 没有 `users / roles / permissions / members / available-roles` 对外接口 | 这是现有管理面的硬依赖。要么迁到 controlplane，要么先删掉这些页面与权限初始化逻辑；在此之前不能退役旧 API |
| 项目样本读模型与按 commit 读标注 | `saki-api/src/saki_api/modules/project/api/http/project.py`、`saki-api/src/saki_api/modules/annotation/api/http/annotation.py` | `saki-web/src/pages/project/ProjectSamplesAnnotations.tsx`、`ProjectOverview.tsx`、`ProjectCommitDetail.tsx`、`hooks/project/useProjectSampleList.ts`、`pages/dataset/DatasetDetail.tsx` 依赖 `project samples / label-counts / annotations at commit / dataset samples` | 当前 public API 只提供 `DELETE /datasets/{dataset_id}/samples/{sample_id}` 与 `GET/POST /projects/{project_id}/samples/{sample_id}/annotations`，没有 project sample list、dataset sample list、label-counts、annotations-at-commit | 这是标注工作区的基础读模型，应优先迁。否则前端主工作区、提交详情、数据集详情都无法切换到 controlplane |
| 项目版本化与标签管理 | `saki-api/src/saki_api/modules/project/api/http/branch.py`、`commit.py`、`label.py` | `saki-web/src/App.tsx` 保留 `branches / commits` 路由；`ProjectBranches.tsx`、`ProjectCommits.tsx`、`ProjectCommitDetail.tsx`、`ProjectSettings.tsx`、`services/api/real.ts` 直接依赖 `branches / commits / labels` | `public-api.yaml` 没有 `branches / commits / labels` 路径 | `branch / commit / label` 需要作为同一组版本化能力迁移；这组能力同时被工作区、提交详情、导出、loop/prediction 依赖，不适合拆散处理 |
| 标注 working/draft/sync/commit pipeline | `saki-api/src/saki_api/modules/annotation/api/http/annotation.py` | `saki-web/src/hooks/annotation/useWorkingDraftPipeline.ts`、`ProjectSamplesAnnotations.tsx`、`services/api/real.ts` 直接依赖 `working / drafts / drafts:batch / drafts/commit / sync` | 当前 public API 没有这组路径，只保留“直接创建/读取正式标注”的最小接口 | 需要作为一条完整工作流迁移，不建议只补单个 endpoint；否则前端的草稿、冲突检测、批量提交语义都会断裂 |
| 导入主工作区收口（dataset images / project annotations） | `saki-api/src/saki_api/modules/importing/api/http/dataset_import.py`、`project_import.py`、`bulk.py` | `saki-web/src/pages/import/ProjectImportWorkspace.tsx` 仍直接调用 `prepareDatasetImageImport`、`prepareProjectAnnotationImport`、`bulkUploadSamples` | 当前 public API 只有 upload session + `projects/{project_id}/datasets/{dataset_id}/imports/annotations:prepare|execute` + `imports/tasks`；缺少 dataset image import，且注解导入 contract 也与前端现用 contract 不一致 | 不建议再补一套旧接口；应尽快统一成一套新的 upload-session + prepare/execute contract，并同步改前端工作区 |
| 项目导出能力 | `saki-api/src/saki_api/modules/project/api/http/export.py` | `saki-web/src/App.tsx` 保留 `/projects/:projectId/export`；`ProjectExportWorkspace.tsx` 与 `services/api/real.ts` 直接依赖 `io-capabilities / exports/resolve / exports/chunk` | `public-api.yaml` 没有 `io-capabilities`、`exports/resolve`、`exports/chunk` | 如果导出工作区继续保留，就必须迁；否则应先删除导出页面与对应入口 |
| runtime 业务面：loop / round / prediction / plugin catalog | `saki-api/src/saki_api/modules/runtime/api/http/query.py`、`endpoints/*.py`、`runtime.py` | `saki-web/src/App.tsx` 保留 `loops / prediction-tasks` 路由；`ProjectLoopOverview.tsx`、`ProjectLoopCreate.tsx`、`ProjectLoopConfig.tsx`、`ProjectLoopDetail.tsx`、`ProjectPredictionTasks.tsx` 直接依赖 `loops / rounds / tasks / predictions / runtime/plugins` | 当前 public API 完全没有 `loops / rounds / tasks query / predictions / runtime/plugins` 这组路径 | 这不是“观测增强”，而是当前产品业务面本身。要么整体迁到新的 controlplane public API，要么先承认 runtime 业务面尚未迁完，不能退役旧 API |
| 模型 registry | `saki-api/src/saki_api/modules/runtime/api/http/model.py` | `saki-web/src/App.tsx` 保留 `/projects/:projectId/models`；`ProjectModels.tsx`、`ProjectPredictionTasks.tsx` 依赖 `models:publish-from-round / models list/detail / promote / artifact download` | 当前 public API 没有 model registry 路径 | 如果 model registry 仍是产品面的一部分，就必须迁；如果准备拿掉，必须先删页面并处理 prediction/model 依赖，而不是只删旧后端 |

## 二、可废弃

| 能力 | 旧来源 | 当前依赖证据 | 处置建议 |
| --- | --- | --- | --- |
| `runtime/executors` 旧 alias | `saki-api/src/saki_api/modules/runtime/api/http/runtime.py` | `saki-controlplane/internal/modules/system/apihttp/legacy_runtime_api_cleanup_test.go` 已明确要求 `/runtime/executors` 从 public API 中消失；`openapi_smoke_test.go` 也要求该路径返回 `404` | **不要**在 controlplane 里复活这个 alias。前端若还需要宿主观测页，应直接改成 `agent` 语义的新页面 |
| 旧 bulk 直写接口：`samples:bulk-import`、`annotations:bulk` | `saki-api/src/saki_api/modules/importing/api/http/bulk.py` | 当前在 `saki-web/src` 中未发现页面直接调用；只有 `services/api/interface.ts` 与 `services/api/real.ts` 还保留客户端声明 | 在前端切到新的 upload-session + prepare/execute contract 后，可以直接废弃，不需要迁到 controlplane |
| 未发现当前依赖的便捷接口：`branches/minimal`、`branches/master`、`commits/tree`、`labels/batch` | `saki-api/src/saki_api/modules/project/api/http/branch.py`、`commit.py`、`label.py` | 在 `saki-web / scripts / docs` 中未检索到对应调用 | 不需要为了“接口齐全”而迁移；后续若真有需要，再从主能力派生 |
| public runtime-domain 操作口 | `saki-api/src/saki_api/modules/runtime/api/http/runtime.py` 中的 `/runtime/domain/status`、`:connect`、`:disconnect`、`:reconnect`、`/runtime/loops:resume-maintenance-paused` | 在 `saki-web / scripts / docs` 中未检索到对应调用 | 若新架构采用 role 健康检查、relay/broker 或内部运维面，这组旧 public API 可以直接废弃，不应默认迁入 public API |

## 三、待产品 / 架构确认

| 能力 | 旧来源 | 当前依赖证据 | 需要确认的问题 | 建议 |
| --- | --- | --- | --- | --- |
| 首次安装、自助注册、本地密码生命周期 | `saki-api/src/saki_api/modules/access/api/http/auth.py`、`saki-api/src/saki_api/modules/system/api/http/system.py` | 当前前端仍有 `Setup / Register / ChangePassword` 页面 | 新主线到底保留“本地用户初始化与自助注册”，还是改成 bootstrap principal / 外部统一认证？ | 先冻结认证模型，再决定迁还是删；在模型冻结前，不要误以为这一块已经迁完 |
| 全局 release / desired-state / update-attempt 管理面 | `saki-api/src/saki_api/modules/runtime/api/http/runtime.py` | `saki-web/src/App.tsx` 仍保留 `/runtime/releases` 路由，`RuntimeReleases.tsx` 直接依赖这组接口 | 新方向是否还要由 controlplane 统一托管 agent/plugin 发布与滚动更新？还是拆到独立 admin plane / 外部制品系统？ | 这是架构决策，不宜先拍脑袋迁 1:1；但在决策明确前，也不能宣称旧 runtime 运维面已完成迁移 |
| associated import 模式 | `saki-api/src/saki_api/modules/importing/api/http/project_import.py` | `ProjectImportWorkspace.tsx` 暴露 `associated` 模式，并直接调用 `prepareProjectAssociatedImport / executeProjectAssociatedImport` | 新 public API 是否还保留“项目关联资产导入”这一模式，还是收敛成更小的 import surface？ | 尽快做产品确认；若不保留，应先从前端移除此模式 |

## 四、建议的下一步执行顺序

1. 先补 `sample read model + branch/commit/label + working/draft/sync`。
   这是标注主工作区切 controlplane 的最短关键路径。
2. 再补 `loop / round / prediction / plugin / model`。
   这组能力是当前 runtime 业务面，不补就不能说“业务已迁完”。
3. 并行收敛 `import / export`。
   这里更适合统一 contract，而不是继续兼容旧 bulk/旧 path。
4. 单独冻结两项架构决策。
   一项是认证模型；一项是 release/update 管理面。
5. 最后再处理前端删旧入口与旧 API 退役。
   包括 `/runtime/executors`、`Register/Setup`、未使用便捷接口与旧客户端声明。
