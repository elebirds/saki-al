# Saki Re-architecture Migration Gap Checklist

> 截止 2026-03-20，本清单用于判断旧 `saki-api / saki-dispatcher / saki-executor` 是否已经可以退役。

## 状态说明

- `[x]` 已确认主路径已迁移到 `saki-controlplane / saki-agent`
- `[-]` 已有部分实现，但还没有形成与旧系统等价的外部能力
- `[ ]` 已确认缺口，旧仓库仍承载该能力或其替代能力尚未落地
- `[?]` 当前只看到代码痕迹，还需要进一步核对是否仍被真实使用

## 一、结论

- [ ] **不能直接退役旧三段式仓库**
  - 原因 1：`controlplane + agent` 已经跑通当前 runtime 主闭环，但旧 `saki-api` 的业务/运维 API 仍有明显未迁切片。
  - 原因 2：旧 `saki-dispatcher` 的 admin 控制面与 runtime-domain 桥接治理面没有在新主线形成等价替代。
  - 原因 3：Go 版 `saki-agent` 目前仍是最小宿主闭环，不等价于旧 Python `saki-executor` 的完整插件/缓存/更新宿主。
  - 原因 4：根级脚本、生成链、部署文档仍直接引用旧仓库。

## 二、`saki-api -> saki-controlplane` 迁移清单

### 2.1 已确认迁移的业务主路径

- [x] **认证最小闭环**
  - `login / me / permission-check` 已在 `public-api` 暴露。
- [x] **项目基础能力**
  - 项目创建、查询、项目与数据集关联/解除关联/明细查询已落到 `controlplane`。
- [x] **数据集基础能力**
  - 数据集创建、分页查询、详情、更新、删除已落到 `controlplane`。
- [x] **样本删除**
  - `DELETE /datasets/{dataset_id}/samples/{sample_id}` 已落地。
- [x] **标注基础能力**
  - 项目上下文的样本标注创建、查询已落地。
- [x] **制品最小闭环**
  - durable upload init/complete/cancel、asset 详情、download sign 已落地。
- [x] **导入新主路径**
  - import upload session、annotation import prepare/execute、task/result 查询已落地。
- [x] **runtime 基础观测与命令**
  - `runtime summary / agents / cancel task` 已落地。

### 2.2 已确认缺口

- [ ] **Access 管理能力未迁全**
  - 旧 `access` 里除 `auth` 外，还有 `resource_member / role / role_permission / user / user_system_role`。
  - 新 `controlplane` 目前只确认暴露了 `login / me / require-permission`。
- [ ] **Project 版本化能力未迁**
  - 旧 `project` 中的 `branch / commit` 结构仍在旧仓库。
  - 新 `public-api` 里没有对应外部接口。
- [ ] **Project 标签管理未迁**
  - 旧 `label` schema/接口仍在旧仓库。
  - 新 `public-api` 中未看到对应项目标签 CRUD。
- [ ] **Project export 能力未迁**
  - 旧仓库仍有导出 profile、resolve、chunk 等一整套 export API。
  - 新 `controlplane` 未暴露对应出口。
- [ ] **Annotation draft / working area / full sync 未迁**
  - 旧仓库仍有 `draft.py` 与 `sync.py` 语义。
  - 新 `controlplane` 当前只有“直接创建/读取正式标注”的主路径。
- [ ] **Sample 读取面未迁全**
  - 旧 `storage/api/sample.py` 有 `SampleRead / ProjectSampleRead` 等读取模型。
  - 新 `public-api` 当前确认了样本删除与标注接口，但未确认有等价 sample list/detail/project-sample 读取面。
- [ ] **Model Registry 未迁**
  - 旧仓库仍有 `publish-from-round / list models / get model / promote / artifact download-url`。
  - 新 `controlplane` 未暴露这组接口。
- [ ] **Runtime 运维 API 未迁**
  - 旧仓库仍有 `runtime plugins / releases / desired-state / update-attempts / runtime-domain status/connect`。
  - 新 `controlplane` 未暴露等价 public API。

### 2.3 已有替代，但需产品/接口收敛决策

- [-] **Import bulk 语义已重构，但不是一对一路径迁移**
  - 旧仓库有 `samples:bulk-upload`、`samples:bulk-import`、`annotations:bulk`。
  - 新主线改成了 upload session + prepare/execute task 模式。
  - 需要明确：旧 bulk 直写接口是要继续保留兼容语义，还是正式废弃。

### 2.4 仍需深挖

- [?] **旧 `storage` 模块中的个别读模型是否只剩 schema，还是仍被前端依赖**
- [?] **旧 `system` 模块是否还有未迁运维/健康类接口**

## 三、`saki-dispatcher -> saki-controlplane runtime` 迁移清单

### 3.1 已确认迁移的 runtime 主干

- [x] **agent 注册/心跳 ingress**
- [x] **scheduler / delivery / recovery role 拆分**
- [x] **`runtime_task + task_assignment + agent_command` 新真相**
- [x] **`pull` 为主、`direct` 为辅、`relay` 可选的 delivery 模式**
- [x] **assign/cancel/complete/recovery 的最小闭环**
- [x] **relay 会话快照 `agent_session`**

### 3.2 已确认缺口

- [ ] **旧 dispatcher admin 控制面没有等价替代**
  - 旧 `dispatcher_admin.proto` 里有 `StartLoop / PauseLoop / ResumeLoop / StopLoop / ConfirmLoop / StopRound / RetryRound / DispatchTask / RuntimeDomainStatus / RuntimeDomainReconnect`。
  - 新主线当前只确认暴露 `runtime summary / agents / cancel task`。
- [ ] **旧 runtime-domain bridge 治理面未迁**
  - 旧 dispatcher 明确承担与 API runtime-domain 的内部桥接治理。
  - 新主线虽然移除了这条旧桥，但原先对应的“连接状态/重连/启停治理面”没有形成替代接口。
- [ ] **STDIN 命令台没有替代方案**
  - 旧 dispatcher 有 `stdin_cmd.go`。
  - 新主线尚未看到等价的本地运维入口。

### 3.3 已有代码雏形，但没有对外收口

- [-] **loop / round / step 领域代码仍在，但未形成新的外部控制面**
  - 新 `controlplane/runtime` 中仍有 `round_repo`、`loop_machine`、`round_machine`、`advance_round.go`。
  - 需要明确这部分是保留并继续迁移，还是降级为内部遗留代码并逐步删除。

### 3.4 仍需深挖

- [?] **旧 dispatcher 的 `runtime_update.sql` 与 update 相关控制面，是否应并入新的 runtime release/agent update 体系**
- [?] **旧 dispatcher 的 `controlplane_*` SQL/服务里，是否还有前端或脚本仍在依赖的查询口径**

## 四、`saki-executor -> saki-agent` 迁移清单

### 4.1 已确认迁移的最小 agent 闭环

- [x] **agent 注册、心跳、运行中 task 回报**
- [x] **`pull` delivery 主路径**
- [x] **`relay` delivery 可选路径**
- [x] **本地 slot 并发准入**
- [x] **control server**
- [x] **通用 worker 子进程协议与 launcher**

### 4.2 已确认缺口

- [ ] **插件发现/注册体系未迁**
  - 旧 `saki-executor` 有 `PluginRegistry` 与插件目录扫描。
  - 新 `saki-agent` 当前只接受 `AGENT_WORKER_COMMAND_JSON`，没有等价插件注册面。
- [ ] **宿主能力探测未迁**
  - 旧 `saki-executor` 有 host capability / accelerator probe / GPU/MPS 识别。
  - 新 `saki-agent` 当前配置面没有等价能力探测配置，也没有看到 richer capability publish。
- [ ] **asset cache 未迁**
  - 旧 `saki-executor` 有 `AssetCache`。
  - 新 `saki-agent` 当前主路径未见等价缓存层。
- [ ] **runtime updater / release activation 未迁**
  - 旧 `saki-executor` 有 `RuntimeUpdater`。
  - 新 `saki-agent` 当前没有对应更新激活主路径。
- [ ] **环境准备/venv/profile 体系未迁**
  - 旧 `saki-executor` 有 environment factory、uv profile installer、venv cache、profile selector。
  - 新 `saki-agent` 当前是“通用 worker 命令执行器”。
- [ ] **训练/选样等高层 orchestration service 未迁**
  - 旧 `saki-executor` 有 `TaskManager`、training data / sampling / artifact uploader 等服务。
  - 新 `saki-agent` 目前把这层职责下沉给 worker 子进程。

### 4.3 需要决策

- [-] **是否还需要保留旧 executor 那种“胖宿主”**
  - 若新方向是“薄 agent + 外部 worker 协议”，则上面部分能力不一定要原样迁移。
  - 但在正式宣布退役 `saki-executor` 前，必须先明确这些能力是“会迁移”还是“正式放弃”。

## 五、根级脚本 / 文档 / 生成链 清单

### 5.1 已确认已切换

- [x] **默认 README 主叙事已经切到 `controlplane + agent`**
- [x] **默认 `docker-compose.yml` 已切到 `saki-controlplane-public-api / saki-controlplane-runtime / saki-agent`**

### 5.2 已确认缺口

- [ ] **`deploy.sh` 仍直接操作旧三段式**
  - 仍创建 `saki-api` / `saki-executor` 数据目录。
  - 仍启动 `saki-api` / `saki-dispatcher`。
  - 仍用 `saki-api` 作为健康等待对象。
- [ ] **`DEPLOYMENT.md` 仍以 `saki-api` 为部署主路径**
- [ ] **`scripts/sync_schema.sh` 仍依赖 `saki-api` 的 alembic**
- [ ] **`scripts/gen_grpc.sh` 仍向 `saki-api / saki-executor / saki-dispatcher` 生成 stub**
- [ ] **`scripts/check_dispatcher_cn_logs.sh` 仍直接依赖 `saki-dispatcher`**

### 5.3 仍需深挖

- [?] **`dist/`、镜像构建产物、CI 流程里是否还有旧三段式引用**
- [?] **前端或插件示例文档里是否还有旧 runtime/executor 心智残留**

## 六、旧仓库退役前置门槛

- [ ] **门槛 1：业务 API 缺口闭合或明确宣布废弃**
  - 尤其是 `branch / commit / label / export / draft / sync / model / runtime release`。
- [ ] **门槛 2：runtime admin/ops 替代面落地**
  - 至少要给出旧 dispatcher admin 控制面的保留、替代或废弃决策。
- [ ] **门槛 3：agent 宿主边界冻结**
  - 要明确“薄 agent + worker 协议”是否就是最终方向。
- [ ] **门槛 4：根级部署/脚本/文档/生成链去除旧依赖**
- [ ] **门槛 5：完成后再处理旧目录**
  - 先改为 archived/legacy stub 也可以，但不能在上述门槛未过时直接删除。

## 七、建议的后续执行顺序

- [x] **先做 public API 业务缺口盘点收敛**
  - 已新增 `docs/superpowers/plans/2026-03-20-saki-public-api-gap-disposition.md`。
  - 已把 `branch / commit / label / export / draft / sync / model / runtime release` 以及 `auth/system`、`RBAC/member`、`sample read`、`loop/prediction/plugin`、`import` 收口成 `必须迁移 / 可废弃 / 待确认` 三类。
- [ ] **再做 runtime admin 面决策**
  - 决定 loop/round/task/admin 控制面是否继续保留。
- [ ] **然后冻结 agent 宿主方向**
  - 明确是否还要迁 plugin/cache/update/env 这类“胖宿主”能力。
- [ ] **最后再做旧仓库退役 cleanup**
  - 包括脚本、文档、proto 生成链、legacy 目录与 worktree 清理。
