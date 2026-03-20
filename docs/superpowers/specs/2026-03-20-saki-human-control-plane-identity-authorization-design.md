# Saki 人类控制面身份与授权设计说明

日期：2026-03-20

## 1. 文档目标

本文档冻结 `saki-controlplane` 中 `system / rbac / user / init` 相关能力的下一版设计。

本次设计同时满足以下约束：

- 功能必须覆盖旧 `saki-api` 中的 `setup / register / change-password / refresh-token / system-status / system-types / system-settings / users / roles / permissions / members`。
- 允许重做交互语义与 API 语义，但不允许功能缺失。
- 当前系统主要是科研用系统，短期内不以对接外部 OAuth / OIDC 为前提。
- 仍然要为未来外接统一身份源预留边界，但不为此引入不必要的复杂度。
- 设计必须与新的 `controlplane + agent` 主线兼容，并明确区分“人类控制面角色”和“controlplane 部署角色”。

本文档不覆盖 `agent` 控制链路、relay/broker 传输细节、runtime 调度状态机本身；它只定义人类控制面的身份、会话、授权、初始化与全局设置模型。

## 2. 对旧 `saki-api` 的复盘

旧 `saki-api` 并不是“原型失败”，而是“原型期为了速度形成的耦合没有在架构升级时被拆开”，最终导致以下结构性问题：

| 问题 | 旧表现 | 根因 | 对新设计的启示 |
| --- | --- | --- | --- |
| 认证、用户、系统初始化、系统设置互相穿透 | 注册是否允许由系统设置控制；`setup` 里直接创建角色、用户、授权；密码修改逻辑与会话生命周期脱钩 | `identity / session / authorization / bootstrap / settings` 没有独立边界 | 必须拆成显式领域模块，禁止再靠 service 间隐式调用维持语义 |
| 协议命名与真实语义不一致 | 旧接口使用 `OAuth2PasswordRequestForm`、`/login/access-token`、`/login/refresh-token`，但本质是本地 JWT 签发 | 原型期借用了熟悉命名，但没有真的采用标准协议体系 | 新版要么真的接标准协议，要么明确采用一方协议，不能继续“看起来像 OAuth，实际不是” |
| refresh token 只是长寿命 JWT | 无服务端 session family、无 rotation、无 replay 检测、无精确撤销 | 早期仅考虑“能续签”，没把“会话治理”当成独立问题 | 新版必须引入显式 session 存储，把 refresh token 从“可验证字符串”改成“可治理会话” |
| 初始化语义过弱 | “系统是否初始化”基本等价于“是否已有用户” | 没有安装态模型 | 新版必须把安装态建模成显式状态，而不是从业务表数量反推 |
| 主体模型只服务于人类用户 | 后续 runtime / dispatcher / executor 无法自然并入统一主体体系 | 一开始没有抽象出“principal”作为统一主体锚点 | 新版要保留统一 principal 抽象，但人类与 agent 的身份语义不能强行混在一起 |
| RBAC 与页面需求耦合 | 不少接口更像“给现有页面供数的后端”而不是稳定的控制面 API | API 从页面倒推，没有独立领域模型 | 新版 API 要围绕领域能力组织，再让前端适配，而不是反过来 |

结论不是“旧方案完全错误”，而是：

- 旧方案适合原型验证。
- 旧方案不适合作为长期的 `controlplane` 身份与授权骨架。
- 新版不能再按旧 Python service 结构直接平移。

## 3. 当前约束与设计原则

### 3.1 当前约束

- 近期不存在强需求去接企业级外部 IdP。
- 当前主要客户端仍是 `saki-web`，其次才可能有脚本/CLI。
- 系统还处于快速开发期，没有线上已部署存量需要兼容；因此数据库与 API 语义都允许做未发布重整。
- 仍需考虑从旧 `saki-api` 数据库迁移历史用户、角色、成员和系统设置数据。
- `controlplane` 本身已经明确存在多个部署 role，这些 role 的配置与运行职责不应混入用户 RBAC。

### 3.2 设计原则

1. 本地优先，不伪装标准协议。  
   在没有真正接入 OAuth / OIDC 的前提下，不再继续借用 `OAuth2PasswordRequestForm` 一类伪标准语义。

2. 分层清晰，不把“账号”“会话”“权限”“安装态”“系统设置”揉成一个 access 模块。  
   这几类概念必须是独立领域。

3. 人类主体与 agent 主体共享授权框架，但不共享身份实现。  
   统一的是 `principal` 和 permission evaluation；不同的是登录方式、凭据类型、会话治理方式。

4. 先把一方本地身份系统做好，再为未来 federation 留薄缝。  
   预留能力可以有，但不能反客为主。

5. resource authorization 保持克制。  
   第一阶段不引入完整 FGA/ReBAC 引擎；项目/数据集成员关系仍采用“成员 + 资源角色”的直接模型。

6. 部署角色与授权角色分离。  
   `public-api / scheduler / supervisor / relay / admin` 这类 controlplane 进程角色，和 `super_admin / project_owner / dataset_member` 这类业务授权角色不是一个维度。

7. 兼容的是历史数据，不是历史错误协议。  
   对旧密码哈希、旧用户/角色/成员数据要提供迁移路径；但不继续把“前端先 SHA-256 再提交”保留为正式新协议。

## 4. 方案比较

### 4.1 方案列表

| 方案 | 描述 | 优点 | 缺点 |
| --- | --- | --- | --- |
| 方案 1：旧语义平移 | 继续内建本地账号体系，基本按旧 `saki-api` 语义迁到 Go | 迁移快；前端改动小 | 把旧耦合原样搬入新 controlplane，后续仍会反复返工 |
| 方案 2：完全外置 IdP | controlplane 只做授权，身份认证完全交给外部 OAuth / OIDC | 长期最标准；与行业主流企业系统一致 | 当前需求与部署现实不匹配；为科研系统引入过重外部依赖 |
| 方案 3：本地优先的分层式身份系统 | controlplane 内建 `identity + credential + session + authorization + bootstrap + settings`，同时保留未来 federation 接缝 | 既满足当前落地，又避免旧结构复活；未来可平滑外接 IdP | 比简单平移多一轮设计与建模成本 |

### 4.2 对比表

| 评估维度 | 方案 1：旧语义平移 | 方案 2：完全外置 IdP | 方案 3：本地优先分层式 |
| --- | --- | --- | --- |
| 当前科研系统适配度 | 中 | 低 | 高 |
| 实现复杂度 | 低 | 高 | 中 |
| 长期可维护性 | 低 | 高 | 高 |
| 对未来接统一身份源的兼容性 | 低 | 高 | 中高 |
| 对当前前端迁移的平滑度 | 高 | 中低 | 中高 |
| 是否能解决旧 `saki-api` 的结构性问题 | 低 | 高 | 高 |
| 是否会过度投资未来能力 | 低 | 高 | 低 |

### 4.3 推荐方案

推荐采用方案 3：**本地优先的分层式身份系统**。

原因如下：

- 它承认当前现实：短期内没有外部 OAuth / OIDC 的落地条件。
- 它解决旧问题：会话、初始化、权限、用户、设置会被拆成清晰的领域边界。
- 它保留未来演进空间：后续若真要接外部 IdP，只需要替换“凭据验证来源”，而不是推翻整个授权与会话模型。

这意味着新版设计的基本立场是：

- 身份权威目前在 `controlplane` 内。
- 授权权威也在 `controlplane` 内。
- future federation 只是扩展点，不是当前主线。

## 5. 总体边界设计

### 5.1 模块划分

建议将当前过于宽泛的 `access` 语义拆成三个显式模块：

- `identity`
  - 负责人类账号、资料、密码凭据、会话生命周期
- `authorization`
  - 负责角色、权限目录、系统角色绑定、资源成员关系
- `system`
  - 负责安装态、系统类型元信息、系统设置

其中：

- `identity` 回答“你是谁，如何验证，当前会话是否有效”
- `authorization` 回答“你能做什么”
- `system` 回答“系统是否完成安装，系统允许哪些全局策略”

### 5.2 两类 role 必须显式区分

#### A. controlplane 部署 role

这是进程运行职责，不是用户权限。典型值包括：

- `public-api`
- `scheduler`
- `supervisor`
- `relay`
- `admin`

它们决定某个 `saki-controlplane` 实例暴露哪些内部能力、启动哪些后台 loop、订阅哪些内部事件。

#### B. 业务授权 role

这是 principal 在业务域里的操作权限。典型值包括：

- 系统角色：`super_admin`、`system_operator`、`annotator_admin`
- 资源角色：`project_owner`、`project_manager`、`project_member`、`dataset_owner`、`dataset_member`

这两类 role 绝不能复用同一套枚举或表结构。

### 5.3 principal 统一抽象

为了兼容未来 `agent` 与内部系统主体，建议保留 `principal` 作为全局授权锚点：

- `human_user` 对应人类账号
- `agent` 对应执行面宿主
- `internal_service` 对应 controlplane 内部系统主体

但第一阶段只完整实现 `human_user` 的 identity / credential / session 流程。  
`agent` 仍走自己的接入协议，只在授权模型上与 `principal` 汇合。

## 6. 领域模型

### 6.1 核心实体

| 实体 | 作用 | 关键字段 |
| --- | --- | --- |
| `iam_principal` | 全局主体锚点 | `id`、`kind`、`display_name`、`status` |
| `iam_user` | 人类用户资料 | `principal_id`、`email`、`username`、`full_name`、`avatar_asset_id`、`state` |
| `iam_password_credential` | 本地密码凭据 | `principal_id`、`password_hash`、`password_algo`、`must_change_password`、`password_changed_at` |
| `iam_refresh_session` | refresh 会话真相 | `id`、`principal_id`、`family_id`、`token_hash`、`expires_at`、`revoked_at`、`rotated_from`、`replay_detected_at` |
| `authz_role` | 系统级角色定义 | `id`、`key`、`scope_kind`、`name`、`built_in`、`mutable` |
| `authz_role_permission` | 角色到权限目录的映射 | `role_id`、`permission` |
| `authz_system_binding` | principal 与系统角色的绑定 | `principal_id`、`role_id` |
| `authz_resource_membership` | principal 在项目/数据集上的成员关系 | `resource_kind`、`resource_id`、`principal_id`、`role_key` |
| `system_installation` | 安装态单例记录 | `install_state`、`setup_at`、`setup_by_principal_id` |
| `system_setting` | 全局设置值 | `key`、`value_json`、`updated_by_principal_id` |

### 6.2 为什么保留 `principal`

保留 `principal` 不是为了提前做“超级统一身份平台”，而是为了避免后面再次出现“人类账号、agent 宿主、内部系统主体各自一套权限锚点”的问题。

新的边界应该是：

- `principal` 只负责“授权语义上的主体”
- `iam_user` 只负责人类资料
- `iam_password_credential` 只负责本地密码验证
- `iam_refresh_session` 只负责会话续签与撤销

这样做的直接好处是：

- 人类登录方式以后可以替换
- agent 接入方式以后可以演进
- `authorization` 无需知道具体登录机制

### 6.3 system role 与 resource role 的设计取舍

系统角色与资源角色采用不同策略：

| 类别 | 第一阶段设计 |
| --- | --- |
| 系统角色 | 支持内建角色 + 自定义角色；权限目录由代码定义，角色绑定由数据库管理 |
| 资源角色 | 采用内建角色集合，不做用户自定义资源角色 |

这样设计的原因是：

- 系统管理面有自定义角色需求，适合继续保留角色管理能力。
- 项目/数据集成员关系更像“协作权限模板”，第一阶段没有必要引入可编程资源角色。
- 这能显著降低实现复杂度，同时覆盖当前产品功能。

## 7. 安装态与系统初始化模型

### 7.1 安装态不再从“是否已有用户”反推

建议引入显式安装态：

- `uninitialized`
- `ready`

第一阶段不引入更多安装态枚举；只要把“未安装”和“已完成初始化”区分清楚即可。

### 7.2 `setup` 的事务语义

`POST /system/setup` 的行为固定为一个事务性用例：

1. 校验当前安装态必须为 `uninitialized`
2. 初始化内建系统角色
3. 创建首个 `human_user` principal
4. 创建首个本地密码凭据
5. 绑定 `super_admin` 系统角色
6. 写入 `system_installation = ready`
7. 初始化系统设置默认值
8. 创建初始登录会话并返回首个 session 对

这样处理后：

- `setup` 不再只是“创建第一个用户”
- 它是系统安装完成的唯一入口
- 前端完成 setup 后无需额外再执行一次 login

### 7.3 `system/status` 的新语义

建议保留 `/system/status` 路径，但重定义响应语义：

```json
{
  "install_state": "uninitialized | ready",
  "allow_self_register": true,
  "version": "controlplane build version"
}
```

这里的 `allow_self_register` 来自 `system_setting`，而不是由前端自行推导。

## 8. 身份与会话模型

### 8.1 登录语义

`POST /auth/login` 使用明确的一方请求体：

```json
{
  "identifier": "user@example.com",
  "password": "plaintext-over-https"
}
```

第一阶段不继续沿用 OAuth 表单协议。
密码在 HTTPS 连接内以明文提交，由服务端统一完成密码哈希与校验；旧的“前端预哈希密码格式”不再保留。
本地密码凭据默认采用服务端 `Argon2id` 哈希策略。

登录成功后返回：

- `access_token`
- `refresh_token`
- `expires_in`
- `user`
- `must_change_password`

### 8.2 access token 与 refresh token 的分工

| 类型 | 设计 |
| --- | --- |
| `access_token` | 短寿命签名令牌，默认 10 分钟，用于每次 API 调用 |
| `refresh_token` | 长寿命不透明随机串，默认 30 天，只用于换新 session，由服务端落库存储其 hash |

这里的关键决策是：

- access token 可以保持轻量与近似无状态
- refresh token 必须变成“可治理会话”，不能再只是长寿命 JWT

### 8.3 refresh rotation 与 replay 检测

`POST /auth/refresh` 的规则如下：

1. 客户端提交 refresh token
2. 服务端按 hash 查找当前 `iam_refresh_session`
3. 校验未过期、未撤销、未被替换
4. 生成新的 refresh token 与新的 session 记录
5. 将旧 session 标记为已轮换

如果发现一个已经轮换过的 refresh token 再次被使用，则认为可能发生了 token 泄漏或重放攻击：

- 标记当前 family 为 `replay_detected`
- 撤销该 family 下所有 refresh session
- 要求客户端重新登录

### 8.4 logout 语义

`POST /auth/logout` 默认撤销当前 refresh session；  
如后续需要，可扩展为“退出当前设备”与“退出全部设备”两种模式。

### 8.5 change-password 语义

`POST /auth/change-password` 的推荐语义：

1. 校验旧密码
2. 更新 `iam_password_credential`
3. 清除 `must_change_password`
4. 撤销该用户全部历史 refresh session
5. 为当前调用方签发新的 session 对并返回

这样做的原因是：

- 变更密码后，其他设备应立即失效
- 当前页面不应被迫再次跳回登录页

### 8.6 register 语义

`POST /auth/register` 只在以下条件同时成立时可用：

- `system_installation.install_state = ready`
- `system_setting.auth.allow_self_register = true`

注册成功后：

- 创建新用户 principal 与本地密码凭据
- 绑定默认系统角色
- 直接返回初始 session 对

如果未来需要邮箱验证或邀请制，可以在 `identity` 内扩展，但不作为本次第一阶段设计前提。

### 8.7 旧凭据兼容与渐进升级

为了兼容旧 `saki-api` 数据，新的本地密码体系需要显式区分“当前凭据方案”和“历史凭据方案”。

建议 `iam_password_credential` 增加 `scheme` 字段，第一阶段至少支持：

- `password_argon2id`
- `legacy_frontend_sha256_argon2`

其中：

- `password_argon2id` 表示服务端直接对 HTTPS 内提交的原始密码做 `Argon2id`
- `legacy_frontend_sha256_argon2` 表示旧库中遗留的 `Argon2(SHA256(password))`

迁移策略固定为：

1. 旧库导入时，历史 `hashed_password` 进入新凭据表，`scheme = legacy_frontend_sha256_argon2`
2. 新 `/auth/login` 只接受 HTTPS 内提交的原始密码，不接受“客户端已 SHA-256”作为正式协议
3. 服务端在验证旧凭据时，先对原始密码执行一次 SHA-256，再校验遗留哈希
4. 旧凭据一旦登录成功，立即升级写回为 `password_argon2id`
5. 用户改密、管理员重置密码、`setup/register` 新建用户，统一只写 `password_argon2id`

这样可以同时满足：

- 历史用户数据不丢失
- 新客户端协议保持干净
- 用户只需成功登录一次即可自动完成凭据升级

### 8.8 为什么不保留前端密码哈希协议

旧前端“先 SHA-256 再提交”的约定不作为新协议保留，原因如下：

- 它不能替代 HTTPS，只是把密码换成另一个可重放的静态口令
- 它对 XSS、恶意前端代码或浏览器本地泄漏没有额外保护
- 它会把 Web、CLI、脚本客户端都绑死在一个私有约定上
- 它会污染未来与 OIDC / WebAuthn / PAKE 的演进边界

因此新协议明确改为：

- 应用层传输原始密码
- 传输层必须依赖 HTTPS
- 服务端统一进行 `Argon2id` 哈希与校验
- 历史前端哈希方案只作为服务端兼容旧数据的验证分支存在，不再作为客户端契约

## 9. 授权模型

### 9.1 permission catalog 由代码定义

权限目录仍建议由代码定义，而不是完全由数据库自由扩展。原因如下：

- 权限名需要稳定、可审计、可测试
- 前后端和策略判断都依赖确定的 permission 集合
- 对当前系统规模而言，没有必要把 permission 本身也做成可运营化配置

数据库只存：

- 角色定义
- 角色到权限的映射
- principal 到角色/成员关系的绑定

### 9.2 系统权限

系统权限用于：

- 用户管理
- 角色管理
- 系统设置管理
- 项目/数据集管理面的全局操作

这部分仍按 RBAC 处理。

### 9.3 资源权限

资源权限用于：

- 项目成员管理
- 数据集成员管理
- 面向具体资源的读写操作判断

第一阶段的资源授权模型固定为：

- `resource_kind + resource_id + principal_id + role_key`

即：

- 一个 principal 在一个项目上可拥有一个项目角色
- 一个 principal 在一个数据集上可拥有一个数据集角色

如果未来真的需要更细粒度的共享、条件表达式或跨层继承，再考虑演进到 FGA/ReBAC 体系；第一阶段不提前引入。

### 9.4 为什么当前不引入独立 FGA/ReBAC

第一阶段明确不引入 `OpenFGA / SpiceDB / Zanzibar-style` 独立授权系统。

原因如下：

- 当前资源种类和共享关系还没有复杂到需要图关系引擎
- 当前最主要的问题是边界混乱，而不是授权表达能力不足
- 过早引入独立 FGA 会增加写路径一致性、排障和运维复杂度
- 现阶段 `RBAC + resource membership` 已足够覆盖 `system / project / dataset` 的授权场景

但授权层仍要按未来可迁移方式实现：

- 统一 `principal`
- 统一 permission catalog
- 授权判断收口到 `authorization` 模块
- 业务代码不得散落自行拼装成员关系和权限规则

只有当后续出现以下信号时，才重新评估是否引入 FGA/ReBAC：

- 组织/团队/用户组及嵌套关系成为一等概念
- 资源之间出现复杂继承链、委托关系或条件授权
- 需要统一回答“谁能访问什么、为什么有权限”
- controlplane 内部进一步拆分后，需要共享授权基础设施

### 9.5 权限变更生效策略

默认策略如下：

- refresh token 续签时重新装载最新权限
- access token 失效时间足够短，默认 10 分钟内完成权限收敛

这意味着：

- 用户被禁用、密码修改、显式 logout 这类高优先事件，需要立即撤销 refresh session
- 角色绑定与成员关系变更，不要求强制中断当前 access token，只要求在下一轮 refresh 后收敛

这比“每个请求都回源校验 session 状态”更简单，也更符合当前科研系统的复杂度约束。

## 10. API 设计

### 10.1 `init / system`

| Endpoint | 说明 |
| --- | --- |
| `GET /system/status` | 返回安装态、自注册开关、版本信息 |
| `GET /system/types` | 返回任务类型、数据集类型等静态元信息 |
| `POST /system/setup` | 完成首次安装，返回首个管理员会话 |
| `GET /system/settings` | 返回系统设置 schema + values |
| `PATCH /system/settings` | 更新系统设置 |

### 10.2 `auth`

| Endpoint | 说明 |
| --- | --- |
| `POST /auth/login` | 账号密码登录 |
| `POST /auth/refresh` | 刷新 access token 与 refresh token |
| `POST /auth/logout` | 注销当前 refresh session |
| `GET /auth/me` | 返回当前用户资料、系统角色、有效权限摘要 |
| `POST /auth/register` | 自助注册并返回初始会话 |
| `POST /auth/change-password` | 修改密码并轮换当前会话 |

### 10.3 `users`

| Endpoint | 说明 |
| --- | --- |
| `GET /users` | 分页列出用户 |
| `POST /users` | 管理员创建用户，默认 `must_change_password = true` |
| `GET /users/{user_id}` | 读取用户详情 |
| `PATCH /users/{user_id}` | 更新用户资料或状态；禁用用户时立即撤销其 refresh sessions |
| `DELETE /users/{user_id}` | 软删除用户并撤销其会话 |
| `GET /users/{user_id}/system-roles` | 查询用户系统角色绑定 |
| `PUT /users/{user_id}/system-roles` | 覆盖式更新用户系统角色绑定 |

### 10.4 `roles / permissions`

| Endpoint | 说明 |
| --- | --- |
| `GET /roles` | 列出系统角色 |
| `POST /roles` | 创建自定义系统角色 |
| `GET /roles/{role_id}` | 读取角色详情 |
| `PATCH /roles/{role_id}` | 更新自定义角色的元数据与权限映射；内建角色只允许调整显示属性，不允许改 key |
| `DELETE /roles/{role_id}` | 删除未被保护约束阻止的自定义角色；内建角色不可删除 |
| `GET /permissions/system` | 返回系统权限目录 |
| `GET /permissions/resource` | 返回项目/数据集资源权限目录与内建资源角色定义 |

### 10.5 `members`

| Endpoint | 说明 |
| --- | --- |
| `GET /projects/{project_id}/members` | 列出项目成员 |
| `PUT /projects/{project_id}/members/{principal_id}` | 设置项目成员角色 |
| `DELETE /projects/{project_id}/members/{principal_id}` | 移除项目成员 |
| `GET /datasets/{dataset_id}/members` | 列出数据集成员 |
| `PUT /datasets/{dataset_id}/members/{principal_id}` | 设置数据集成员角色 |
| `DELETE /datasets/{dataset_id}/members/{principal_id}` | 移除数据集成员 |

## 11. 前后端启动链新语义

建议前端的 boot flow 固定为：

1. 调用 `GET /system/status`
2. 若 `install_state = uninitialized`，进入 setup 页面
3. 若系统已 ready，则检查本地 session
4. access token 不可用时，调用 `POST /auth/refresh`
5. refresh 成功后调用 `GET /auth/me`
6. 进入受保护应用

这样可以把原先零散的“系统状态检测、refresh、权限自检”收敛成单一启动链。

## 12. 与旧接口的迁移映射

| 旧接口语义 | 新接口语义 |
| --- | --- |
| `POST /login/access-token` | `POST /auth/login` |
| `POST /login/refresh-token` | `POST /auth/refresh` |
| `POST /register` | `POST /auth/register` |
| `POST /change-password` | `POST /auth/change-password` |
| `GET /status` | `GET /system/status` |
| `GET /types` | `GET /system/types` |
| `POST /setup` | `POST /system/setup` |
| `GET /settings/bundle` | `GET /system/settings` |
| `PATCH /settings` | `PATCH /system/settings` |

迁移原则如下：

- 路径不必强行兼容旧命名，只要前端与文档同步切换即可。
- 旧“伪 OAuth”命名统一退役。
- 旧 `saki-api` 的 user/role/member 语义保留功能，不保留历史实现结构。
- 旧 access token 与旧 refresh token 默认不兼容，切换到新 controlplane 后要求重新登录。

## 13. 与旧数据的兼容策略

本次重构需要兼容的对象主要是“旧数据库中的业务真相”，而不是“旧客户端协议”。

明确策略如下：

| 对象 | 策略 |
| --- | --- |
| 历史用户资料 | 迁移到 `iam_principal + iam_user` |
| 历史密码哈希 | 迁移到 `iam_password_credential`，按 `legacy_frontend_sha256_argon2` 标记 |
| 历史系统角色与绑定 | 迁移到 `authz_role / authz_role_permission / authz_system_binding` |
| 历史项目/数据集成员关系 | 迁移到 `authz_resource_membership` |
| 历史系统设置 | 迁移到新 `system_setting` |
| 历史 access token / refresh token | 不迁移；新系统上线后统一失效 |

这条边界必须保持清晰：

- 兼容的是数据库内的历史状态
- 不兼容的是旧的 session wire format 和旧的前端密码协议

## 14. 与未来外部 IdP 的关系

虽然当前不以外部 OAuth / OIDC 为前提，但新版仍建议预留以下薄接缝：

1. `identity` 内部不要把“密码验证”写死为唯一认证方式。  
   具体做法是把 credential provider 设计为可扩展枚举，目前只实现 `local_password`。

2. `iam_user` 与 `principal` 不绑定“必须由本地密码创建”。  
   后续若要支持 `federated_identity`，只需要增加外部主体映射表。

3. `authorization` 不依赖具体登录方式。  
   这样未来即使换成 OIDC 登录，角色绑定、资源成员、系统设置权限都不需要重做。

这里的重点是“预留缝”，不是“现在就做完整 federation”。

## 15. OAuth/OIDC 兼容边界

新版设计不保留完整 OAuth/OIDC server 语义，也不自建完整 OAuth 授权服务器。

### 15.1 不保留的内容

- 不继续使用 `OAuth2PasswordRequestForm`
- 不继续使用 `/login/access-token`、`/login/refresh-token` 这类伪 OAuth 命名
- 不实现 `authorization code / PKCE / consent / client registry / discovery / jwks`
- 不引入重型 OAuth server 框架作为第一阶段基础设施

### 15.2 保留的兼容概念

- `Bearer` access token 语义
- `access token / refresh token` 的职责分离
- token 中稳定的主体/过期时间语义
- `401 / 403` 的标准错误语义
- 可扩展的 credential/provider 边界

### 15.3 为什么不直接做一个 OAuth 系统

对当前科研系统而言，真正需要的是：

- 本地账号与密码凭据
- 可治理的 refresh session
- 清晰的 RBAC 与 membership
- 稳定的 setup / register / change-password / settings

而不是一个完整的 OAuth 产品能力栈。  
过早引入完整 OAuth server，只会让当前系统承担额外的 client/scopes/redirect/consent 复杂度，却不能实质解决当前重构主问题。

## 16. 实施顺序建议

### 阶段 1：冻结领域与存储模型

- 重整 `access` 相关 migration
- 引入 `identity / authorization / system` 新模块边界
- 设计并落地 `principal / user / credential / refresh_session / role / binding / membership / installation / setting`

### 阶段 2：先打通 `init + auth + system`

- `system/status`
- `system/setup`
- `system/types`
- `auth/login`
- `auth/refresh`
- `auth/me`
- `auth/register`
- `auth/change-password`
- `system/settings`

这是前端启动链与安装链的最短闭环。

### 阶段 3：完成 `users + roles + permissions + members`

- 用户 CRUD
- 系统角色 CRUD
- 系统权限目录
- 资源权限目录
- 项目/数据集成员管理

### 阶段 4：切前端并退役旧 `saki-api` 入口

- `saki-web` 切换到新 public API
- 删除旧伪 OAuth 命名
- 删除旧 `saki-api` 对应的 access/system/rbac 对外入口

## 17. 最终结论

对于当前 Saki，最合适的路线不是：

- 继续按旧 `saki-api` 语义平移，也不是
- 立即以外部 OAuth / OIDC 为中心重做整套认证体系

而是：

**在 `saki-controlplane` 中构建一套本地优先、分层清晰、会话可治理、授权边界明确的人类控制面身份系统，并仅为未来 federation 保留薄扩展缝。**

这条路线同时满足：

- 当前科研系统可落地
- 旧 `saki-api` 结构性问题得到修复
- 新 `controlplane + agent` 主线不再被历史 access 设计拖住
