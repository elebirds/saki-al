# saki-api

`saki-api` 是 Saki 的后端事实源，承载业务域与 Runtime 域 API，并提供 Runtime Domain gRPC 服务给 dispatcher。

## 1. 模块定位

`saki-api` 负责：

1. 项目、分支、提交、标注、权限、导入导出等业务域接口。
2. Runtime 相关查询与操作接口（loop/round/step/task/prediction）。
3. 与 dispatcher 的 runtime domain 内部桥接。

`saki-api` 不负责：

- 训练任务实际执行。
- dispatcher 调度逻辑。

## 2. 技术栈

- FastAPI
- SQLModel / SQLAlchemy Async
- Pydantic v2
- PostgreSQL
- Redis
- MinIO/S3 兼容对象存储

## 3. 目录概览

```text
saki-api/src/saki_api/
├── main.py
├── app/
├── core/
├── infra/
└── modules/
    ├── system/
    ├── access/
    ├── storage/
    ├── project/
    ├── importing/
    ├── annotation/
    └── runtime/
```

## 4. 安装与启动

安装依赖：

```bash
cd saki-api
uv sync
```

启动服务：

```bash
make run
```

等价命令：

```bash
uv run uvicorn saki_api.main:app --reload
```

测试：

```bash
uv run pytest
```

## 5. 数据库与 schema 管理

在仓库根目录执行：

```bash
bash scripts/sync_schema.sh
```

强制重建（危险）：

```bash
bash scripts/sync_schema.sh --reset
```

## 6. 关键环境变量

### 6.1 必要项

- `DATABASE_URL`
- `SECRET_KEY`
- `INTERNAL_TOKEN`

### 6.2 常用项

- API：`API_V1_STR`、`BACKEND_CORS_ORIGINS`
- 对象存储：`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET_NAME`
- 缓存：`REDIS_URL`、`REDIS_KEY_PREFIX`
- Runtime Domain：`RUNTIME_DOMAIN_GRPC_BIND`、`RUNTIME_DOMAIN_GRPC_SERVER_ENABLED`
- Dispatcher 桥接：`DISPATCHER_ADMIN_TARGET`、`DISPATCHER_ADMIN_TIMEOUT_SEC`
- 日志：`LOG_LEVEL`、`LOG_DIR`、`LOG_FILE_NAME`

## 7. 接口与装配方式

1. 所有 HTTP 路由统一挂载到 `API_V1_STR`（默认 `/api/v1`）。
2. 路由通过模块注册器动态装配（`get_app_modules`）。
3. 运行时 gRPC 服务在应用生命周期内启动与停止。

## 8. 跨模块契约

1. `saki-api` 是业务真相源。
2. 执行器不直接写业务数据库。
3. runtime 执行观测主键对齐 `task_id`。

## 9. 排障建议

1. 启动失败并报 DB 错误
- 检查 `DATABASE_URL` 是否为 PostgreSQL URL。

2. 上传失败
- 检查 `MINIO_*` 配置与 bucket。

3. runtime 桥接异常
- 检查 dispatcher 的 `RUNTIME_DOMAIN_TARGET` 是否可达 API runtime-domain 端口。
