# saki-executor

GPU 训练执行器，主动连接 `saki-api` 的 gRPC 控制面，执行训练、选样、日志上报与制品上传。

## 运行

```bash
cd saki-executor
uv sync
uv run python -m saki_executor.main
```
