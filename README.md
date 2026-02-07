# Saki

视觉主动学习闭环平台，包含：

1. `saki-api`：唯一后端事实源（项目/分支/提交/任务/指标/事件）。
2. `saki-web`：前端交互界面（数据集、标注、任务与结果可视化）。
3. `saki-executor`：GPU 执行器，主动连接 API 的 gRPC 控制面执行训练与选样。

## 仓库结构

- `saki-api/`：FastAPI + SQLModel
- `saki-web/`：React + Vite + TypeScript
- `saki-executor/`：Python 执行器（gRPC 双向流 + 插件机制）
- `proto/`：运行时控制协议 `runtime_control.proto`
- `scripts/gen_grpc.sh`：统一 gRPC 代码生成脚本

## 快速开始

### 1) 基础环境

```bash
cp env.example .env
```

建议使用 `uv` 管理 Python 依赖。

### 2) 启动 API

```bash
cd saki-api
uv sync
make run
```

### 3) 启动 Executor

```bash
cd saki-executor
uv sync
uv run python -m saki_executor.main
```

### 4) 启动 Web

```bash
cd saki-web
npm install
npm run dev
```

## 文档入口

1. 项目总览：`CLAUDE.md`
2. Runtime 约束：`MODEL_RUNTIME_DESIGN.md`
3. Executor 设计：`saki-executor/EXECUTOR_DESIGN.md`
4. 协议切换发布手册：`RUNTIME_CUTOVER_RUNBOOK.md`
