# Saki API

This is the backend service for the Saki Active Learning Framework.

## Development

Run the server:

```bash
uv run uvicorn main:app --reload
```

## Database

快速开发模式下，服务启动时会自动执行 `SQLModel.metadata.create_all`。
需要重建表结构时，直接删库或删表后重启服务即可。

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
