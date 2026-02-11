# saki-executor

GPU 训练执行器，主动连接 `saki-api` 的 gRPC 控制面，执行训练、选样、日志上报与制品上传。

默认内置插件：

1. `yolo_det_v1`（默认，真实 YOLO 训练 + 增强 IoU 选样）
2. `demo_det_v1`（回退用）

## 运行

```bash
cd saki-executor
uv sync
uv run python -m saki_executor.main
```

如果使用 `yolo_det_v1`，运行环境需具备 CUDA（可选）并可安装 `ultralytics` 依赖。

## 运行时命令

启动后可在当前终端输入：

1. `help`
2. `status`
3. `plugins`
4. `connect`
5. `disconnect [--force]`
6. `stop [job_id]`
7. `loglevel <LEVEL>`
8. `quit` / `exit`

## 设计文档

详见 `EXECUTOR_DESIGN.md`。
