# Saki Model Runtime

This service handles model training, inference, and active learning queries for the Saki framework.

## Development

Managed by `uv`.

```bash
uv sync
uv run uvicorn saki_runtime.main:app --reload
```
