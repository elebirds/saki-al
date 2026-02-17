# Saki IR v1 规范（破坏性冻结版）

## 1. 范围与目标
`saki-ir` v1 定义视觉深度学习标注数据的中间格式（IR），用于可复现、可复用的数据交换。

- Proto 语法：`proto3`
- 外层载体：`EncodedPayload`
- v1 默认 payload codec：`PROTOBUF`
- 可选 payload codec：`MSGPACK`（v1 枚举保留，SDK 当前返回明确未实现错误）
- 支持压缩：`NONE` / `ZSTD`
- checksum：`CRC32C`（Castagnoli）

v1 不做向后兼容，不保留 legacy 字段。

## 2. 坐标系
所有几何均在像素坐标系中定义：

- 原点：左上角
- x 轴：向右
- y 轴：向下

## 3. 核心数据结构
`annotation_ir.proto`（包：`saki.ir.v1`）包含以下核心消息：

- `RectGeometry {x, y, width, height}`
- `ObbGeometry {cx, cy, width, height, angle_deg_cw}`
- `Geometry { oneof shape { rect | obb } }`
- `LabelRecord`
- `SampleRecord`
- `AnnotationRecord`
- `DataItemIR { oneof item { label | sample | annotation } }`
- `DataBatchIR { repeated DataItemIR items }`
- `PayloadHeader` / `PayloadStats` / `EncodedPayload`

### 3.1 Rect 语义（TL）
`RectGeometry` 语义为左上角 + 尺寸：

- `x, y`：左上角坐标
- `width, height`：宽高

约束：`width > EPS` 且 `height > EPS`，`EPS = 1e-6`。

### 3.2 OBB 语义（Center）
`ObbGeometry` 语义为中心点 + 尺寸 + 角度：

- `cx, cy`：中心点
- `width, height`：宽高
- `angle_deg_cw`：顺时针角度（度）

约束：`width > EPS` 且 `height > EPS`。

### 3.3 Rect / OBB 转换公式
Rect TL 转中心：

- `cx = x + width / 2`
- `cy = y + height / 2`

中心转 Rect TL：

- `x = cx - width / 2`
- `y = cy - height / 2`

## 4. OBB 规范化规则
对 `ObbGeometry` 执行以下 normalize：

1. 若 `width < height`，交换 `width` 与 `height`，并执行 `angle_deg_cw += 90`
2. 角度归一化到区间 `[-180, 180)`

推荐实现：

- `angle = (angle + 180) % 360 - 180`

## 5. 非法值规则
对 annotation 的几何与置信度执行严格校验：

- 任意 `NaN` / `Inf`：直接失败
- `Rect/OBB width/height <= EPS`：失败
- `confidence` 必须在 `[0, 1]`
- 错误分类约定：
  `confidence` 违规归类为 `SCHEMA`（记录字段合法性），
  `geometry` 违规归类为 `GEOMETRY`

`label` / `sample` 在 v1 不做强制字段变更。

## 6. Payload 层语义
### 6.1 Header 字段
`PayloadHeader`：

- `schema`：当前固定 `DATA_BATCH_IR`
- `schema_version`：当前固定 `1`
- `codec`：`PROTOBUF`（已实现）/ `MSGPACK`（未实现）
- `compression`：`NONE` 或 `ZSTD`
- `checksum_algo`：`CRC32C`
- `checksum`：对**未压缩 payload 原始字节**计算 CRC32C，类型 `uint32`
- `stats`：统计信息

### 6.2 Stats 字段
`PayloadStats` 字段语义：

- `item_count`：`DataBatchIR.items` 总数
- `annotation_count`：annotation record 数（不是 box 数）
- `sample_count`：sample item 数
- `label_count`：label item 数
- `payload_size`：压缩后 `payload` 字节长度
- `uncompressed_size`：压缩前原始字节长度

### 6.3 编码流程（v1 默认）
1. 校验（必要时先 normalize 后校验）
2. `payload_raw = protobuf_marshal(DataBatchIR)`
3. `checksum = CRC32C(payload_raw)`
4. 若 `len(payload_raw) >= 32768`，使用 `ZSTD(level=3)` 压缩；否则 `NONE`
5. 填充 `PayloadHeader + PayloadStats`
6. 输出 `EncodedPayload {header, payload}`

### 6.4 解码流程
1. 读取 `header`
2. 按 `compression` 还原 `payload_raw`
3. 校验 CRC32C（基于 `payload_raw`）
4. 按 `codec` 反序列化（v1 仅 `PROTOBUF`）
5. 可选执行 normalize，确保输出为规范形式

## 7. 只读 Header 调度
Dispatcher 只读取 `header.stats` 做调度。SDK 提供 `ReadHeader`，可在不解压、不解码 payload 的前提下读取 header。

`ReadHeader` 返回的是 header 只读视图（Go 返回原始 header 指针，Python 返回独立对象副本），调用方不应修改其字段。

## 8. SDK API（v1）
### 8.0 Normalize / Validate 契约
- `Normalize`：原地（in-place）规范化对象。
- `Validate`：不修改输入；实现方式为复制后执行 normalize 校验。

### Python
- `normalize_ir(batch)`
- `validate_ir(batch)`
- `encode_payload(batch, compression_threshold=32768, zstd_level=3)`
- `decode_payload(encoded)`
- `read_header(encoded)`
- `iter_items(batch)`
- `to_dataframe(batch, kind="annotation")`

### Go
- `Normalize(*DataBatchIR) error`
- `Validate(*DataBatchIR) error`
- `Encode(*DataBatchIR, threshold, level) (*EncodedPayload, error)`
- `Decode(*EncodedPayload) (*DataBatchIR, error)`
- `ReadHeader(*EncodedPayload) *PayloadHeader`

## 9. View/Wrapper 使用建议
- View/Wrapper 不引入新模型，proto message 仍是唯一真相。
- 默认无副作用：除显式 `*_inplace` 命名外，View 方法不应修改底层 message。
- Dispatcher 建议只使用 `EncodedPayloadView.Header().Stats()` 做调度。
- Executor 建议使用 `EncodedPayloadView.Decode()` 获取 `DataBatchIR`。
