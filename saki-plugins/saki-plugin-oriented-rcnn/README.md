# saki-plugin-oriented-rcnn

Oriented R-CNN 主动学习插件（面向 Saki 执行器）。

## 功能概览
- 数据准备：将项目数据转换为 DOTA `images/` + `labelTxt/` 结构。
- 训练：基于 MMRotate 训练并产出主模型 `artifacts/best.pth`。
- 评估：输出标准指标 `map50` / `map50_95` / `precision` / `recall`。
- 选样：支持三种策略：
  - `aug_iou_disagreement`
  - `uncertainty_1_minus_max_conf`
  - `random_baseline`

## 环境要求
- Python `>=3.11`
- 包管理器：`uv`
- 依赖 profile（二选一）：
  - CPU：`profile-cpu`
  - CUDA：`profile-cuda`

## 安装
在插件目录执行：

```bash
uv sync --extra dev --extra profile-cpu
```

如果是 CUDA 环境：

```bash
uv sync --extra dev --extra profile-cuda
```

## 开发校验
```bash
uv run python -m compileall src/saki_plugin_oriented_rcnn tests
uv run --extra dev pytest -q
```

## 关键实现说明
- 数据导出固定走 `saki-ir` 的 DOTA 导出能力，避免插件内重复实现几何转换。
- 图片统一转为 PNG，规避 MMRotate 对 `img_suffix` 的单值假设。
- 主动学习的增强一致性策略内部使用 qbox 对齐并做匈牙利匹配，确保分支间 IoU 可比。
- 若环境缺少 `shapely`，IoU 自动回退到 AABB 计算，保证流程不中断（但精度会下降）。

## 运行建议
- 生产环境优先使用 CUDA；CPU 仅建议用于开发联调。
- 若项目标注主要是 OBB，建议 `predict_geometry_mode=auto` 或 `obb`，减少几何信息损失。
- 小样本场景若无独立验证集，会启用 `val_degraded` 逻辑保证流程可执行。

## 常见问题
1. `uv run pytest -q` 提示找不到 `pytest`
- 原因：未启用 `dev` 依赖。
- 处理：改用 `uv run --extra dev pytest -q`。

2. 训练可启动但评估指标异常低
- 检查 `prepare_data` 产物中的 `class_schema.json` 是否与项目标签一致。
- 检查数据是否存在类别严重不平衡，必要时增加样本或调整训练轮次。

3. `aug_iou_disagreement` 与预期差异较大
- 先确认是否安装 `shapely`。缺失时会走 AABB 回退，几何重叠度近似更粗。
