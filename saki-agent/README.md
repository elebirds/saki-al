# saki-agent

`saki-agent` 是驻守计算节点的守护进程，负责：

1. Kernel 生命周期控制（Start/Stop/Kill）。
2. Agent-Kernel `ZMQ over IPC(UDS)` 通道管理。
3. 节点硬件能力上报与健康检查。
4. 本地产物上传（Agent 持有存储凭证，Kernel 不持有）。

## IPC 规范

1. 控制通道：`ipc:///var/run/saki-agent/<kernel_instance_id>.ctl.sock`
2. 事件通道：`ipc:///var/run/saki-agent/<kernel_instance_id>.evt.sock`
3. 目录权限：`0700`
4. socket 权限：`0600`
5. 启动时清理陈旧 socket，退出时 unlink。

## 安全约束

1. 启动前执行 Kernel 环境白名单检查。
2. 拒绝任何 MinIO/AWS 凭证变量注入到 Kernel 进程环境。

## 制品上传

1. Kernel 仅上报本地相对路径（`workspace/output/...`），不持有存储凭证。
2. Agent 使用 MinIO Go SDK 流式上传本地文件。

## 配置（环境变量）

1. `SAKI_AGENT_RUN_DIR`（默认：`<启动目录>/.saki-agent/run`）
2. `SAKI_AGENT_CACHE_DIR`（默认：`<启动目录>/.saki-agent/cache`）
3. `LOG_LEVEL`（默认 `info`）
4. `ENABLE_STDIN_COMMANDS`（默认 `true`）
5. `RUNTIME_CONTROL_TARGET`（默认 `127.0.0.1:50051`）
6. `INTERNAL_TOKEN`（默认 `dev-secret`，与 dispatcher 保持一致）
7. `SAKI_AGENT_EXECUTOR_ID`（默认主机名）
8. `SAKI_AGENT_NODE_ID`（默认主机名）
9. `SAKI_AGENT_RUNTIME_KIND`（默认 `saki-agent`）
10. `SAKI_AGENT_VERSION`（默认 `dev`）
11. `SAKI_AGENT_HEARTBEAT_INTERVAL_SEC`（默认 `10`）
12. `SAKI_AGENT_CONNECT_TIMEOUT_SEC`（默认 `5`）
13. `SAKI_AGENT_RECONNECT_INITIAL_BACKOFF_SEC`（默认 `2`）
14. `SAKI_AGENT_RECONNECT_MAX_BACKOFF_SEC`（默认 `30`）
15. `SAKI_AGENT_KERNELS_DIR`（默认自动探测：`./saki-kernels/kernels` 或 `../saki-kernels/kernels`）
16. `SAKI_AGENT_MINIO_ENDPOINT`
17. `SAKI_AGENT_MINIO_ACCESS_KEY`
18. `SAKI_AGENT_MINIO_SECRET_KEY`
19. `SAKI_AGENT_MINIO_BUCKET`
20. `SAKI_AGENT_MINIO_PREFIX`（默认 `runtime-artifacts`）
21. `SAKI_AGENT_MINIO_USE_SSL`（默认 `false`）

## 插件加载

1. Agent 仅从 `SAKI_AGENT_KERNELS_DIR` 下扫描 `**/kernel.yaml`（或 `kernel.yml`）加载插件能力。
2. 不再支持通过 CSV 手工注入插件 ID。
3. 若未扫描到任何插件，注册仍会继续，但 dispatcher 无法派发业务 step。

## Stdin 命令台

1. `status|st`
2. `kernels`
3. `cache`
4. `drain [on|off]`
5. `kill <kernel_id>`
6. `reconnect`（触发与 dispatcher 的 stream 重连）
7. `help|h|?`
8. `exit|quit`
