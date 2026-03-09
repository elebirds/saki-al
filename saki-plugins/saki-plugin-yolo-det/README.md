# saki-plugin-yolo-det

`yolo_det_v1` 是 Saki 默认检测插件，覆盖训练、评估、预测与主动学习选样。

## 1. 定位

- 插件 ID：`yolo_det_v1`
- 版本：`3.0.0`
- SDK 约束：`>=4.0.0`
- 支持加速器：`cuda`、`mps`、`cpu`

## 2. 能力范围

任务类型：

- `train`
- `score`
- `predict`
- `eval`
- `custom`

选样策略：

- `aug_iou_disagreement`
- `uncertainty_1_minus_max_conf`
- `random_baseline`

## 3. 安装

CPU：

```bash
uv sync --extra profile-cpu
```

CUDA：

```bash
uv sync --extra profile-cuda
```

MPS：

```bash
uv sync --extra profile-mps
```

## 4. 开发校验

```bash
uv run python -m compileall src/saki_plugin_yolo_det tests
uv run --extra dev pytest -q
```

## 5. 核心配置字段

训练参数：

- `epochs`
- `batch`
- `imgsz`
- `patience`
- `workers`

推理与选样参数：

- `predict_conf`
- `aug_iou_enabled_augs`
- `aug_iou_iou_mode`
- `aug_iou_boundary_d`

模型来源参数：

- `model_source`
- `model_preset`
- `model_custom_ref`

## 6. 运行建议

1. 生产优先 `cuda`。
2. 无 GPU 环境可使用 `cpu` 或 macOS `mps`。
3. 先用 demo 插件跑通链路，再切换 yolo 插件验证效果。

## 7. 常见问题

1. 依赖安装失败
- 检查 profile 与平台匹配。

2. 训练启动但效果异常
- 检查数据准备质量和标签分布。

3. 参数不生效
- 检查前端提交是否通过 `config_schema` 验证。
