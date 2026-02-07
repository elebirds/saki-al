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
