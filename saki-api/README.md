# Saki API

This is the backend service for the Saki Active Learning Framework.

## Development

Run the server:

```bash
uv run uvicorn main:app --reload
```

## Database Migration (Alembic)

初始化（首次）：

```bash
cd saki-api
alembic -c alembic.ini upgrade head
```

生成迁移（后续变更）：

```bash
cd saki-api
alembic -c alembic.ini revision --autogenerate -m "your message"
alembic -c alembic.ini upgrade head
```

默认已关闭 `create_all` 自动改表（`DB_AUTO_CREATE_TABLES=false`）。
