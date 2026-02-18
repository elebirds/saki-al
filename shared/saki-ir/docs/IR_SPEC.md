# Saki IR v1 规范（权威）

> 本文档是 `saki-ir` v1 的单一事实来源（single source of truth）。
> 除非明确声明，否则规范条款均为 **MUST**。

<a id="1-scope-and-goals"></a>
## 1. 范围与目标
- `saki-ir` v1 仅定义视觉标注数据的中间表示（IR）与传输封装。
- v1 是**破坏性冻结版本**：不做向后兼容，不保留 legacy 字段。
- 本规范不定义存储层、数据库 schema、任务调度策略。
- Proto 使用 `proto3`；字段编号/名字/类型在 v1 内冻结。

<a id="2-coordinate-system"></a>
## 2. 坐标系定义
- 坐标系为像素坐标（pixel coordinates）。
- 原点在图像左上角。
- `x` 向右增大，`y` 向下增大。

<a id="3-data-structures"></a>
## 3. 数据结构概览
- 几何：`RectGeometry`、`ObbGeometry`、`Geometry(oneof)`。
- 记录：`LabelRecord`、`SampleRecord`、`AnnotationRecord`。
- 批结构：`DataItemIR(oneof)`、`DataBatchIR(repeated items)`。
- 传输层：`EncodedPayload{header, payload}`、`PayloadHeader`、`PayloadStats`。

<a id="4-rect-semantics"></a>
## 4. Rect 语义（Top-Left）
`RectGeometry{x, y, width, height}` 语义固定为：
- `x, y`：左上角（top-left）坐标
- `width, height`：宽高

合法性：
- `width > EPS`
- `height > EPS`
- `EPS = 1e-6`
- 任意分量出现 `NaN/Inf` 必须失败

转换公式：
- TL -> center：`cx = x + width / 2`，`cy = y + height / 2`
- center -> TL：`x = cx - width / 2`，`y = cy - height / 2`

<a id="5-obb-semantics"></a>
## 5. OBB 语义（Center + angle_deg_ccw）
`ObbGeometry{cx, cy, width, height, angle_deg_ccw}` 语义固定为：
- `cx, cy`：中心点
- `width, height`：宽高
- `angle_deg_ccw`：从 **+x 轴** 逆时针旋转到 OBB 的 **width 边方向**（单位：度）
  - 坐标系仍是屏幕坐标（`x` 向右，`y` 向下）
  - 因此 `angle_deg_ccw = 0` 时 width 方向朝 `+x`
  - `angle_deg_ccw = +90` 时 width 方向朝 `+y`（向下）

合法性：
- `width > EPS`
- `height > EPS`
- 任意分量出现 `NaN/Inf` 必须失败

<a id="6-obb-normalization"></a>
## 6. OBB 规范化规则（必须严格一致）
输入 OBB 规范化步骤：
1. 若 `width < height`：交换 `width`/`height`，并执行 `angle_deg_ccw += 90`
2. 将角度归一化到 `[-180, 180)`
3. 若结果为 `180`，必须映射到 `-180`

补充：
- `width == height` 时**不**触发 swap。

<a id="7-vertices-and-aabb"></a>
## 7. 顶点与 AABB 定义
### 7.1 顶点顺序（Rect/OBB）
本规范区分两套顶点顺序：

1. **局部角点顺序（local corner order）**
   - API：`ObbToVerticesLocal` / `obb_to_vertices_local`
   - 返回顺序：`TL, TR, BR, BL`
   - 角点定义来自局部坐标 `(u,v)`：
     - `(-w/2,-h/2), (+w/2,-h/2), (+w/2,+h/2), (-w/2,+h/2)`
   - 该顺序不是屏幕排序，不得按“最左上点”重排。

2. **屏幕排序角点（screen-sorted order）**
   - API：`ObbToVerticesScreen` / `obb_to_vertices_screen`
   - 返回顺序：`TL, TR, BR, BL`
   - 排序规则：先按 `y`（小在上），`y` 接近时按 `x`（小在左）
   - 用于 UI 渲染、poly8 导出等需要稳定屏幕顺序的场景。

Rect 顶点统一为屏幕顺序：
- API：`RectToVerticesScreen` / `rect_to_vertices_screen`
- 返回顺序：`TL, TR, BR, BL`

重要区分：
- OBB 的 local `TL/TR/BR/BL` 与 screen `TL/TR/BR/BL` 不是同一语义。
- 反例：`angle=30°` 时，local `TL` 不一定是屏幕最左上点。
- 若把 local 角点误当 screen 角点，会导致双视图映射、拟合与导出结果系统偏角。

### 7.2 AABBRectTL
`AABBRectTL` 定义为：
- `x = min(vertices.x)`
- `y = min(vertices.y)`
- `w = max(vertices.x) - min(vertices.x)`
- `h = max(vertices.y) - min(vertices.y)`

<a id="8-invalid-values"></a>
## 8. 非法值与校验失败条件
以下任一情况必须失败：
- 任意 `NaN/Inf`
- `width <= EPS` 或 `height <= EPS`
- `confidence` 不在 `[0, 1]`
- `geometry` 缺失或 `geometry.shape` 缺失

错误分类契约：
- `confidence` 违规归 `ERR_IR_SCHEMA`
- 几何违规归 `ERR_IR_GEOMETRY`

<a id="9-encoded-payload"></a>
## 9. EncodedPayload 编码/解码规范
### 9.1 编码输入与原始字节
- `payload_raw = protobuf_marshal(DataBatchIR)`
- v1 默认 `codec = PROTOBUF`
- `MSGPACK` 枚举保留，但 v1 必须返回“未实现”错误

### 9.2 checksum（覆盖范围）
- `checksum = CRC32C(payload)`
- 算法：Castagnoli
- 覆盖范围是 `EncodedPayload.payload`（压缩后 bytes；`compression=NONE` 时即原始 bytes）

### 9.3 压缩
- 支持 `NONE` / `ZSTD`
- 默认阈值：`32768` bytes
- 默认 `zstd level = 3`
- 不使用 dictionary
- 当 `len(payload_raw) >= threshold` 才可压缩

### 9.4 Header 字段固定约束
- `schema = DATA_BATCH_IR`
- `schema_version = 2`
- `checksum_algo = CRC32C`

### 9.5 Stats 字段语义
- `item_count`：`DataBatchIR.items` 总数
- `annotation_count`：annotation records 数（不是 box 数）
- `sample_count`：sample item 数
- `label_count`：label item 数
- `payload_size`：压缩后 payload 字节长度
- `uncompressed_size`：压缩前 `payload_raw` 字节长度

### 9.6 解码
- 先读 header，校验 CRC32C（覆盖 `payload`）
- 按 compression 解压得到 `payload_raw`
- 按 codec 反序列化
- 可选执行 normalize（SDK 提供开关）

<a id="10-header-only-behavior"></a>
## 10. Header-only 行为
- Dispatcher 只依赖 `header.stats` 调度时，必须不解压、不解码 payload bytes。
- `verify checksum` 仅校验 `payload`，不需要解压、不需要 decode 成 `DataBatchIR`。
- SDK 语义约定：
  - Go `ReadHeader` 返回 header 引用（只读约定）。
  - Python `read_header` 返回 header 副本（copy）。

<a id="11-error-code-contract"></a>
## 11. 错误码契约
- `ERR_IR_SCHEMA`
  - schema/schema_version/checksum_algo 非法
  - confidence 越界或非有限值
  - 缺失必需顶层对象（如 batch/header）
- `ERR_IR_GEOMETRY`
  - geometry/shape 缺失
  - rect/obb 非法（NaN/Inf、宽高 <= EPS）
- `ERR_IR_CODEC_UNSUPPORTED`
  - codec 未实现或未知（含 MSGPACK）
- `ERR_IR_COMPRESSION_UNSUPPORTED`
  - compression 未实现或解压失败
- `ERR_IR_CHECKSUM_MISMATCH`
  - CRC32C 校验不一致

<a id="12-minimal-example"></a>
## 12. 最小示例（语义说明）
最小可读 batch（概念示例）：
- 1 个 `LabelRecord{id="label-1", name="car"}`
- 1 个 `SampleRecord{id="sample-1", width=1920, height=1080}`
- 1 个 `AnnotationRecord{id="ann-1", sample_id="sample-1", label_id="label-1", geometry.rect={x=10,y=20,width=100,height=40}, confidence=0.9}`

该 batch 编码时：
- `payload_raw` 是上述 `DataBatchIR` 的 protobuf bytes
- `checksum` 对 `payload` 计算 CRC32C（`compression=NONE` 时 `payload == payload_raw`）
- `stats.item_count=3`，`stats.annotation_count=1`，`stats.sample_count=1`，`stats.label_count=1`

<a id="13-view-wrapper-guidance"></a>
## 13. View/Wrapper 使用建议
- View/Wrapper 不引入新主模型，proto message 是唯一真相。
- 默认无副作用；任何会修改对象的方法必须显式命名 `*_inplace`。
- `EncodedPayloadView.header/stats` 返回副本（copy），避免误改源对象。
- Dispatcher 推荐用 `EncodedPayloadView.header/stats`；Executor 推荐用 `EncodedPayloadView.decode()`。
