# saki-kernel-sdk

`saki-kernel-sdk` 为 Python Kernel 提供统一脚手架：

1. IPC 通讯封装（`emit_metric/log/progress/artifact_local_ready`）。
2. Manifest 软链接落地（只链接，不移动源文件）。
3. 统一异常捕获与事件上报。
4. 平台约定降级变量 `USE_CPU_FOR_LOSS` 的读取与执行入口。

## 约束

1. 只支持 `ipc://` 控制/事件 URI。
2. Kernel 进程环境禁止出现 MinIO/AWS 凭证变量。
3. Kernel 只写本地 `workspace/output`，上传由 Agent 处理。
