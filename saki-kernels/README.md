# saki-kernels

`saki-kernels` 存放纯 AI 逻辑实现，每个 kernel 独立 `uv` 环境与 `kernel.yaml` 声明。

## 目录约定

1. `kernels/<kernel-id>/kernel.yaml`
2. `kernels/<kernel-id>/main.py`（或包入口）
3. 输出产物统一写入 `workspace/output`

## 能力声明

`kernel.yaml` 必须声明：

1. `supported_step_types`
2. `supported_modes`
3. `capabilities`（例如 `supports_mps_loss_cpu_fallback`）

调度器依据能力声明和节点能力做派发匹配。
