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
3. 启动参数：
   - `--minio-endpoint`
   - `--minio-access-key`
   - `--minio-secret-key`
   - `--minio-bucket`
   - `--minio-prefix`（默认 `runtime-artifacts`）
   - `--minio-ssl`
