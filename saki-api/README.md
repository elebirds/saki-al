# Saki API

This is the backend service for the Saki Active Learning Framework.

## Development

Run the server:

```bash
uv run uvicorn saki_api.main:app --reload
```

## Database

数据库结构以 SQLModel 为唯一标准，通过 Alembic 进行迁移管理。

在仓库根目录执行：

```bash
./scripts/sync_schema.sh
```

如需彻底重建（会清空 `public` schema）：

```bash
./scripts/sync_schema.sh --reset
```

如果 PostgreSQL 在 Docker 中运行：

```bash
./scripts/sync_schema.sh --docker
```

## Logging

`saki-api` 使用 `loguru` 统一日志输出，控制台与文件格式如下：

`{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}`

可配置环境变量：

- `LOG_LEVEL`：日志级别（默认 `INFO`）
- `LOG_DIR`：日志目录（默认 `logs`）
- `LOG_FILE_NAME`：日志文件名（默认 `api.log`）
- `LOG_MAX_BYTES`：单文件轮转大小（默认 `20971520`）
- `LOG_BACKUP_COUNT`：保留历史文件数量（默认 `5`）
- `LOG_COLOR_MODE`：控制台颜色模式（`auto|on|off`，默认 `auto`）
