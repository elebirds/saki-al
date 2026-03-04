# Oriented R-CNN 主动学习插件实施计划

## 1. 目标与范围
- 目标：在 Saki 执行器内交付可运行的 `Oriented R-CNN` 主动学习插件，支持 DOTA 数据格式、训练/评估/预测全链路。
- 范围：
  - 数据准备：项目数据 -> DOTA `images/` + `labelTxt/`。
  - 训练：MMRotate 训练并产出 `artifacts/best.pth`。
  - 评估：输出 `map50`、`map50_95`、`precision`、`recall`。
  - 选样：支持 `aug_iou_disagreement`、`uncertainty_1_minus_max_conf`、`random_baseline`。
  - 运行时：支持 `cuda/cpu` 绑定与降级。

## 2. 已实施内容（当前完成）
- 插件骨架与契约：`plugin.yml`、worker 入口、runtime service 编排完成。
- 配置服务：参数解析、模型来源校验（preset/local/url）、URL 缓存下载完成。
- DOTA 数据准备：
  - 使用 `saki-ir` 导出 DOTA，避免重复实现几何转换。
  - 图像统一转 PNG，规避 MMRotate `img_suffix` 单值约束问题。
  - 写出 `class_schema.json` 与 `dataset_manifest.json`，支持复现与排障。
- 训练与评估：
  - 训练后自动评估，输出 canonical metrics。
  - `best.pth` 统一复制到 `artifacts/` 作为主模型制品。
- 预测与主动学习：
  - 支持模型缓存，减少重复加载开销。
  - 实现增强一致性打分（含逆变换、匈牙利匹配、polygon IoU）。
  - `shapely` 不可用时回退 AABB IoU，保证流程可运行。
- 测试：配置与指标归一化单测已覆盖。

## 3. 关键设计与注释规范（已执行）
- 关键设计点必须写中文注释，至少覆盖以下位置：
  - 配置边界与参数校验策略。
  - 数据格式转换与分割策略（尤其是 split 回捞与 val_degraded）。
  - 主动学习打分公式、权重含义与归一化方式。
  - 算法替代路径（如 shapely 缺失时的回退逻辑）。
- 注释标准：
  - 先写“为什么”，再写“怎么做”。
  - 对影响指标或兼容性的分支必须写注释。
  - 只在关键路径写注释，避免噪声注释。

## 4. 收尾实施步骤（下一阶段）
1. 集成回归
- 在执行器真实流程中串行验证 `prepare -> train -> eval -> score/predict`。
- 验证 `step_runtime_requirements` 与 runtime profile 选择是否符合预期。

2. 测试补强
- 增加 `predict_service` 关键算法单测：
  - `_hungarian_maximize` 匹配正确性。
  - `_polygon_iou` shapely/回退分支一致性。
  - `aug_iou_disagreement` 在边界输入（空预测/单分支）下稳定性。

3. 文档与交付
- 补充 README（安装、依赖 profile、运行示例、常见故障）。
- 明确生产环境建议：
  - CPU 仅用于开发调试；生产建议 CUDA。
  - 无 shapely 时评分精度会下降但不会中断。

## 5. 验收标准
- 功能验收：
  - 五类 step（`train/score/predict/eval/custom`）均可调用。
  - 三类策略均能返回稳定候选样本列表。
- 指标验收：
  - `map50/map50_95/precision/recall` 字段完整且数值在 `[0,1]`。
- 工程验收：
  - `uv run python -m compileall src tests` 通过。
  - `uv run --extra dev pytest -q` 通过。
- 可维护性验收：
  - 关键代码与设计处具备中文注释，能独立解释设计动机与边界条件。
