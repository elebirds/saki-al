# MIGRATION NOTE: OBB 语义切换为 CCW（v1 开发期破坏性变更）

## 结论
- `ObbGeometry` 角度字段语义已统一为 `angle_deg_ccw`（屏幕坐标 CCW）。
- `proto` 仍在 `saki.ir.v1` 命名空间；这是开发期内的破坏性变更，不做旧语义兼容。

## 关键变化
1. 字段名统一为 `angle_deg_ccw`（对应 camelCase: `angleDegCcw`）。
2. 旋转方向统一：
   - `0°`：宽边方向朝 `+x`
   - `+90°`：宽边方向朝 `+y`（向下）
3. 顶点工具分为两类：
   - `obb_to_vertices_local` / `ObbToVerticesLocal`：局部角点顺序
   - `obb_to_vertices_screen` / `ObbToVerticesScreen`：屏幕排序顺序

## 识别旧行为的信号
- 代码中仍使用 `angle_deg_cw`、`angleDegCw`。
- OBB 旋转公式仍使用 CW 版本（例如 `rx = dx*cos + dy*sin; ry = -dx*sin + dy*cos`）。
- 导出 poly8 使用 local 顶点顺序但期望屏幕排序。

## 迁移建议
1. 全仓替换字段名：`angle_deg_cw -> angle_deg_ccw`。
2. 所有 OBB 旋转计算切换到屏幕 CCW 公式。
3. 需要稳定屏幕顺序的场景（UI/poly8）统一改用 `*_vertices_screen`。
4. 回归测试至少覆盖：`angle=0/+90` 方向、local/screen 顺序、YOLO OBB roundtrip。
