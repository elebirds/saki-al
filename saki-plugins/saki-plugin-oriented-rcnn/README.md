# saki-plugin-oriented-rcnn

`oriented_rcnn_v1` 是面向 OBB 场景的插件实现，服务于 Saki 执行器主动学习链路。

## 1. 定位

- 插件 ID：`oriented_rcnn_v1`
- 版本：`1.0.0`
- SDK 约束：`>=4.0.0`
- 支持加速器：`cuda`、`cpu`

## 2. 能力范围

- 任务类型：`train`、`score`、`predict`、`eval`、`custom`
- 策略：
  - `aug_iou_disagreement`
  - `uncertainty_1_minus_max_conf`
  - `random_baseline`

## 3. 依赖与安装

- Python `>=3.11`
- 包管理：`uv`

CPU：

```bash
uv sync --extra dev --extra profile-cpu
```

CUDA：

```bash
uv sync --extra dev --extra profile-cuda
```

## 4. 开发校验

```bash
uv run python -m compileall src/saki_plugin_oriented_rcnn tests
uv run --extra dev pytest -q
```

## 5. 关键配置

- 训练：`epochs`、`batch`、`imgsz`、`workers`
- 推理：`predict_conf`
- 选样：`aug_iou_enabled_augs`、`aug_iou_iou_mode`、`aug_iou_boundary_d`
- 模型来源：`model_source`、`model_preset`、`model_custom_ref`

## 6. 工程约束

1. 数据转换优先复用 `saki-ir` 导出能力。
2. 配置输入以 `plugin.yml` schema 为准。
3. 插件不直接写业务数据库，由执行器统一回传。

## 7. 常见问题

1. CUDA 依赖安装困难
- 先验证 CPU profile，再切 CUDA。

2. 指标异常偏低
- 检查样本质量、标签分布、训练轮次设置。

3. 选样差异大
- 检查几何相关依赖是否齐全。

实施细节见：`IMPLEMENTATION_PLAN.zh-CN.md`。
