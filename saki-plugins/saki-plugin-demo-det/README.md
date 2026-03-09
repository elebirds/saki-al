# saki-plugin-demo-det

`demo_det_v1` 是用于联调的演示插件，重点验证执行链路，不依赖真实训练框架。

## 1. 定位

- 插件 ID：`demo_det_v1`
- 版本：`3.0.0`
- SDK 约束：`>=4.0.0`
- 支持加速器：`cpu`

## 2. 适用场景

1. dispatcher <-> executor 通道联调。
2. Runtime 页面日志与状态链路验证。
3. CI/本地快速冒烟。

## 3. 能力范围

- 任务类型：`train`、`score`、`predict`、`eval`、`custom`
- 策略：
  - `uncertainty_1_minus_max_conf`
  - `aug_iou_disagreement`
  - `random_baseline`

## 4. 安装与测试

```bash
cd saki-plugins/saki-plugin-demo-det
uv sync --extra dev --extra profile-cpu
uv run --extra dev pytest -q
```

## 5. 关键配置

来自 `plugin.yml`：

- `epochs`
- `batch_size`
- `steps_per_epoch`

## 6. 注意事项

1. 这是 mock 插件，不代表真实模型效果。
2. 适合验证“流程通不通”，不适合验证“指标好不好”。
