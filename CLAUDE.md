# Saki Project Guide (视觉主动学习系统)

## 1. 项目定位
Saki 是一个集数据集管理、样本标注（支持版本控制）、模型训练与视觉主动学习于一体的闭环智能标注平台。
通过 "Human-in-the-loop" 流程，利用主动学习算法筛选高价值样本，降低标注成本，提升模型迭代效率。

## 2. 技术栈概览

### Backend (saki-api)
- **Framework**: Python 3.9+ / FastAPI
- **ORM**: SQLModel + SQLAlchemy (Async)
- **Validation**: Pydantic V2
- **Storage**:
  - Metadata: PostgreSQL
  - Object Storage: MinIO (S3 Compatible)
- **Auth**: JWT (python-jose, argon2-cffi)
- **Data/ML**: NumPy, Pandas, Scikit-learn, OpenCV, Pillow

### Runtime (saki-executor)
- **Core**: AsyncIO + gRPC 双向流 (`RuntimeControl.Stream`)
- **Protocol**: protobuf 强类型 `RuntimeMessage.oneof payload`
- **Execution**: 单任务串行执行器 + 插件机制（训练/推理/选样）
- **Communication**: 仅与 `saki-api` gRPC 与对象存储预签名 URL 通信
- **Logging**: Loguru（控制台 + 滚动文件）

### Frontend (saki-web)
- **Framework**: React 18 + Vite + TypeScript
- **UI Library**: Ant Design 5.x(仅使用原子组件) + Tailwind CSS (布局与定制)
- **State Management**: Zustand
- **Graphics/Annotation**: Konva + React-Konva + use-image
- **Networking**: Axios
- **I18n**: i18next

## 3. 架构与设计原则

### 开发状态看板 (Status)
#### saki-api
- **L1 (Physical)**: ✅ 完成 (Asset去重, MinIO上传, Sample逻辑封装)
- **L2 (Logic)**: ✅ 基本完成 (三层架构、标注流水线协议、项目概览与设置界面 已基本就绪)
- **L3 (Experiment)**: ✅ 已落地主链路（Loop/Round/Step + Runtime gRPC + Executor），当前持续收敛在“稳定性、可复现性、指标可信度”。
#### saki-executor
已完成基础闭环（注册/心跳/派发/事件/结果/停止/数据请求/上传票据），当前处于“强类型与可靠性收敛”阶段。

考虑到 GPU 服务器可能被 NAT 阻拦，无法被外网直接访问，设计上采用 Runtime 主动向 saki-api 建立长连接，并保持心跳的方式进行通信。

期望实现一个轻量级的训练执行器，能够从 saki-api 拉取数据和标注，执行训练任务，并将结果（模型制品、日志、评估指标）持久化回 saki-api 以供查询和版本管理。

关于主动学习的选样算法，初期计划实现：
1. **基于不确定性的选样**：最小置信度，1 - min/avg(confidence).
2. **交并比选样**：将样本做简单的增强（如翻转、裁剪），计算原始与增强样本的预测结果的交并比，1 - 交并比。
3. **随机选样**：作为基线，随机选择样本进行标注。
主要是考虑到这两种算法的实现相对简单，不需要深入的模型内部访问，可以统一实现，后续根据需要增加更复杂的选样算法。

此外还需要支持两种训练方式：
- **主动学习策略**：用户一开始只标注了一小部分，每轮训练后根据选样算法选择一批样本进行标注，迭代优化。
- **模拟训练策略**：把当前所有标注样本都用于训练，逐渐增大使用数量，模拟主动学习流程。

### 核心工作流
数据导入 → 样本标注 → 版本快照 → 模型训练 (Runtime) → 主动学习选样 → 迭代优化

### 设计契约 (Model Runtime)
- **单一职责**: `saki-api` 是数据与其关系的 "Source of Truth"；`saki-executor` 是执行器。
- **数据流向**: Executor **不直接写** 业务数据库，只通过 API 拉取数据，并将制品/日志持久化在本地 `runs/{step_id}` 目录。
- **接口风格**: gRPC 双向流（控制 + 事件）+ 对象存储预签名 URL（制品/样本）。

### Runtime v2 语义（简版）
- 统一命名冻结为 `Loop / Round / Step`，不再使用 `ALLoop / Job / JobTask`。
- `Step` 是最小执行单元，所有运行时事件、指标、制品都挂在 `step_id`。
- `StepDispatchKind` 仅有两类：`DISPATCHABLE`（下发 executor）与 `ORCHESTRATOR`（dispatcher 内部执行）。
- 模式策略：
  - `ACTIVE_LEARNING`：每轮结束进入 `WAIT_USER`，仅该模式允许 `confirm`。
  - `SIMULATION`：自动推进，无 `confirm`，支持轮次冷却。
  - `MANUAL`：单轮闭环（默认 `max_rounds=1`）。
- `STOPPING` 需具备重启恢复能力：重启后继续扫描并收敛到 `STOPPED`。


### Saki-API 三层架构协议 (Architecture Protocol)
为了支持 Git-like 的版本回溯和大规模主动学习，后端的核心模型被严格划分为三层。AI 在编写代码时必须识别当前逻辑所属的层级，并遵循该层的设计契约。

#### **L1: 物理数据层 (Physical Data Layer) —— “内容寻址与本体”**
- **定位**：处理文件存储的“物理真实性”，解决“文件在哪”和“是否重复”的问题。
- **核心模型**：
- - **Asset**: 基于 **SHA256 哈希** 的内容寻址。**设计契约**：一旦写入，绝对不可变。去重逻辑由数据库唯一索引强制执行。
- - **Sample**: 逻辑上的“一帧”或“一个对象”。**设计契约**：通过 `asset_group` (Dict) 引用 Asset，实现物理（文件）与逻辑（样本）解耦。
- - **Dataset**: 样本逻辑集合容器。它是数据导入的最小单位。一个 Project 可以关联多个 Dataset（多对多），支持跨项目的数据复用。**设计契约**：仅包含 Sample 引用，禁止直接包含 Asset。

#### **L2: 逻辑标注层 (Annotation Logic Layer) —— “Git-like 版本控制”**

- **定位**：处理“谁在什么时候标注了什么”，实现毫秒级的版本切换。
- **核心模型**：
- - **Annotation**: **绝对不可变记录**。修改逻辑 = `INSERT` 新记录 + `parent_id` 追踪历史。
- - **Commit**: 标注状态的快照点。代表项目在某一时刻的完整“标注视图”。
- - **CAMap (CommitAnnotationMap)**：**性能引擎**。通过 `(commit_id, sample_id, annotation_id)` 索引表，将标注状态固定。
- - **Branch**: 动态指针。指向某个 Commit，代表开发线（如 `master`）或实验线（如 `active-learning-v1`）。
- - **Label**: 标注任务的标签定义。
- - **Project**：整个系统的 Source of Truth 和管理边界。类似于 Git 的 Repository。它持有所有的 Label（标签定义）、Branch（分支）和 Commit（快照）。

* **AI 开发准则**：
* **禁止 `UPDATE` 标注内容**。必须执行“产生新 Annotation -> 创建 Commit -> 更新 CAMap”的事务。
* 查询某版本下的标注必须通过 `CAMap` 关联查询，禁止全表扫描 `Annotation`。

#### **L3: 训练实验层 (Training Experiment Layer) —— “主动学习闭环”**

- **定位**：处理“如何利用标注进行迭代”，解决“实验复现”和“任务调度”的问题。
- **核心模型**：
- - **Loop**: 实验容器。每个 Loop 必须绑定一个独立的 **Branch**，确保实验数据与主分支隔离。
- - **Round**: 单轮执行上下文，记录 `input_commit_id / output_commit_id`。
- - **Step**: 最小执行单元。**设计契约**：必须记录 `step_type / dispatch_kind / resolved_params`。
- - **Metric**: 评估结果。与 Round/Step 聚合关联。
- - **Model**: 模型制品。与 Step 关联，支持按轮次回溯。

### 标注流水线协议 (Annotation Pipeline)
为了平衡实时响应、数据安全与版本严谨性，标注采用三级处理流程：
1. **Working Area (Redis)**: 
   - 触发：实时绘图/Sync 计算。
   - 职责：缓存 OpenCV/LUT 映射结果。支持刷新恢复。
2. **Staging Area (AnnotationDraft 表)**:
   - 触发：用户“切图”（下一张）、手动暂存或离开页面。
   - 职责：将 Redis 中的数据 UPSERT 到数据库草稿表。支持跨设备断点续传。
3. **Formal Commit (Annotation & CAMap)**:
   - 触发：用户点击“提交版本”。
   - 职责：将 Draft 固化为不可变记录。执行后清空对应 Draft。

## 4. 目录结构
```text
saki/
├── saki-api/           # 核心业务后端 (FastAPI)
│   ├── src/saki_api/
│   │   ├── api/        # 路由定义
│   │   ├── core/       # 配置与安全
│   │   ├── db/         # 数据库连接
│   │   ├── models/     # SQLModel 模型 (分层设计: L1/L2/L3/RBAC)
│   │   └── services/   # 业务逻辑
├── saki-executor/      # GPU 执行器（训练/推理/选样）
│   ├── src/saki_executor/
│   │   ├── agent/      # gRPC 客户端与连接生命周期
│   │   ├── steps/      # Step 执行与状态机
│   │   ├── plugins/    # 模型插件
│   │   └── strategies/ # 内置选样策略
├── saki-web/           # 交互式前端 (React)
│   ├── src/
│   │   ├── components/ # 通用组件
│   │   ├── pages/      # 页面视图 (使用 Ant Design)
│   │   ├── store/      # Zustand store
│   │   └── services/   # API 客户端
├── data/               # 本地数据存储 (DB, MinIO, Logs) - gitignored
├── scripts/            # 辅助脚本
├── deploy.sh           # 部署脚本
├── docker-compose.yml  # 容器编排
└── MODEL_RUNTIME_DESIGN.md # Runtime 详细设计文档
```

## 5. 开发指令

### 环境准备
- 复制环境变量示例: `cp env.example .env` (按需修改配置)
- 推荐使用 `uv` 进行 Python 包管理。

### 后端 (saki-api)
在 `saki-api` 目录下:
- **安装依赖**: `uv sync`
- **启动 API**: `make run`
- **运行测试**: `uv run pytest`

### Runtime (saki-executor)
在 `saki-executor` 目录下:
- **安装依赖**: `uv sync`
- **启动执行器**: `uv run python -m saki_executor.main`

### 前端 (saki-web)
在 `saki-web` 目录下:
- **安装依赖**: `npm install`
- **启动开发**: `npm run dev` (默认端口 5173, 会代理请求到后端 8000)
- **构建生产**: `npm run build`

## 6. 代码规范与偏好

### 前端

- **组件风格**: 用于展示的组件尽量保持纯函数风格。
- **状态管理**: 使用 `Zustand` 处理全局状态 (如当前选中的数据集、用户偏好)。
- **样式**: 使用 Ant Design 的 Design Token 和组件，尽量少写自定义 CSS。
- **标注逻辑**: 标注画布逻辑复杂，相关代码应封装在 `components/Canvas` 或类似模块中，与业务逻辑分离。

#### 🎨样式哲学 (Antd + Tailwind)

* **协同原则**: **Antd 负责“物”，Tailwind 负责“空”。**
* 使用 Antd 处理复杂交互组件（如带搜索的分页表格、复杂表单）。
* 使用 Tailwind 处理页面布局（Flex/Grid）、内边距、自定义颜色、响应式显隐。

* **覆盖规范**: 禁止在 `.css` 文件中写样式的覆盖。若需调整 Antd 样式，优先使用 `ConfigProvider` 的 Design Token，其次在 `className` 中使用 Tailwind 的 `!` (important) 修饰符。
* **示例**: `<Table className="mt-4 shadow-sm !rounded-lg" />`

### 后端
- **异步原则 (Async)**: 所有 I/O 操作 (DB, Network) 必须使用 `async/await`。
- **Type Hints**: 100% 类型覆盖，利用 Pydantic 做运行时验证。
- **SQLModel**: 定义 Table 时同时定义 Pydantic Model，避免重复代码。
- **风格**: 遵循 PEP 8，使用 snake_case 命名。
- **错误处理**: 使用 AppException 及其预定义子类统一处理业务错误，避免直接抛出 HTTPException。
- **MVC 分层**: Models (数据结构) / Services (业务逻辑) / API (路由与请求处理)。禁止在 API(Controller)层直接操作数据库 session。如无极端需求，数据库 session 操作均应在 Repository 层完成。大部分的基础 Service 和 Repo 应继承 BaseService 和 BaseRepository，以简化基础 CRUD。
- **继承与复用**: 优先使用组合而非继承，避免深层次继承链。
- **自动包装**: 不应该在 endpoints 中直接使用 ApiResponse 包装返回值。ApiResponse 已经在更高层（如中间件或统一响应处理器）进行包装，以保持业务逻辑的纯粹性。

## 7. 部署
- 项目包含 `docker-compose.yml` 用于启动 Postgres, MinIO 和相关服务。
- 生产环境建议将 `DATABASE_URL` 指向 PostgreSQL。
- 运行 `./deploy.sh` 可执行基础部署流程 (需检查脚本具体内容)。

## 8. Copilot/AI/Claude 协作提示。
- 编写 Runtime 相关代码时，**必须** 严格遵守 `MODEL_RUNTIME_DESIGN.md` 中的“强约束”章节。
- 编写 Loop/Round/Step 编排逻辑时，优先对齐 `docs/runtime-loop-round-step-语义计划书-v2.md`（该文档是当前语义基线）。
- 遇到数据库模型问题时，请先查看 `saki-api/src/saki_api/models` 下的文件结构
- 在涉及数据库设计的建议中，优先考虑数据一致性和长期维护成本，而非短期性能提升。

## 9. MCP 建议
- 使用 `context7` 检索最新的 FastAPI 或 React 19 API 文档。
