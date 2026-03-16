# Saki Import 与 Go-Native IR Adapters 设计

日期：2026-03-16

## 1. 目标

本文档定义 `saki-controlplane` 下一阶段的导入重构方向，目标是：

1. 为 `project annotation import` 建立新的控制面实现。
2. 保留现有 `prepare / execute / task / events` 的交互模型。
3. 将 `COCO / YOLO` 格式转换能力迁入 `Go-native saki-ir`，避免长期依赖 Python import 子系统。
4. 明确 `IR Core`、`format adapters` 与 `import orchestration` 的边界。

本阶段重点是为后续完整导入体系打下正确边界，而不是一次性恢复旧 `import_service.py` 的所有能力。

## 2. 现状

当前仓库中：

- `saki-controlplane` 已有：
  - `public-api`
  - `runtime`
  - `annotation` 最小闭环
  - 本地 `mapping sidecar`
- `saki-api` 旧实现中，导入路径仍集中在超大服务 [import_service.py](/Users/hhm/code/saki/saki-api/src/saki_api/modules/importing/service/import_service.py)。
- 旧导入逻辑在格式解析阶段直接依赖 Python `saki-ir`：
  - `load_coco_dataset`
  - `load_yolo_dataset`
  - `split_batch`
- 当前 `shared/saki-ir` 的能力存在明显语言不对称：
  - Go：已有 `codec / normalize / geom / view / transport`
  - Python：在此基础上还有完整 `convert/io`，包括 `COCO / YOLO / VOC / DOTA`

这说明：

1. `IR` 本身是有价值的，值得保留。
2. 现有问题不在 `IR Core`，而在“格式转换器只长在 Python 侧”。
3. 新 import 若直接复用 Python 旧链路，会把长期控制面边界重新拉回 Python。

## 3. 设计结论

本阶段的关键结论如下：

1. **保留 `IR Core`，继续作为 `Go + Python` 双 SDK 的核心规范。**
2. **不保留“通用 Python import engine”作为长期方案。**
3. **`COCO / YOLO` 格式适配迁入 `shared/saki-ir/go`。**
4. **`saki-controlplane` 的 `importing` 模块只做 orchestration，不解析原始格式。**
5. **`project annotation import` 第一阶段保留两段式和任务跟踪：`upload session -> prepare -> execute -> task/result/events`。**
6. **第一阶段仅实现 `COCO bbox -> IR rect` 和 `YOLO det txt -> IR rect`。**
7. **`rect / obb(xywhr) / obb(poly8)` 要在设计层提前留口，但复杂几何第一阶段只设计不实现。**

## 4. IR 策略

### 4.1 保留的部分

`shared/saki-ir` 中以下能力继续作为核心保留：

- proto
- codec
- normalize / validate
- geometry / view
- transport
- error model

这些能力已经在以下位置具备基础实现：

- Go：`shared/saki-ir/go/sakir`
- Python：`shared/saki-ir/python/src/saki_ir`

其中 [IR_SPEC.md](/Users/hhm/code/saki/shared/saki-ir/docs/IR_SPEC.md) 继续作为单一事实来源。

### 4.2 调整的部分

当前 `saki-ir` 把“核心规范能力”和“格式转换器”耦合在一起，而格式转换器主要只在 Python 侧完整存在。新的边界应改成：

- `IR Core`
- `Format Adapters`

即：

- `IR Core` 继续双语言维护
- `Format Adapters` 也进入长期治理，但允许分阶段补齐

### 4.3 核心几何保持不变

`IR Core Geometry` 继续只保留：

- `rect`
- `obb`

不会把 `poly8` 提升为新的 IR 核心几何类型。

`poly8`、`obb_xywhr` 等形态只作为 adapter 输入形式存在，在进入 IR 时统一转换为：

- `rect`
- `obb`

这样可以保持：

- proto 稳定
- normalize/view 稳定
- controlplane 内部几何种类稳定

## 5. Format Adapter 设计

### 5.1 所属位置

`COCO / YOLO` adapter 应位于：

```text
shared/saki-ir/go/
```

而不是：

```text
saki-controlplane/internal/modules/importing/
```

因为格式适配是围绕 IR 的基础能力，不属于控制面业务逻辑。

建议未来目录形态为：

```text
shared/saki-ir/go/
├── sakir/
│   ├── codec.go
│   ├── normalize.go
│   ├── geom.go
│   └── view.go
└── formats/
    ├── coco/
    └── yolo/
```

### 5.2 第一阶段实现范围

第一阶段仅实现：

- `COCO detection bbox -> IR rect`
- `YOLO detection txt -> IR rect`

第一阶段只设计、不实现：

- `COCO segmentation / polygon`
- `YOLO OBB xywhr`
- `YOLO OBB poly8`
- `VOC / DOTA`

### 5.3 输入几何与输出几何分离

adapter 需要显式区分：

- `input_geometry_kind`
- `output_geometry_kind`

例如：

- `rect -> rect`
- `obb_xywhr -> obb`
- `obb_poly8 -> obb`

这能确保未来扩展复杂格式时，不需要改 `IR Core`。

### 5.4 Adapter API

adapter 不应直接返回 controlplane domain 或 repo model，而应返回：

1. `IR batch`
2. 与导入相关的元信息

建议接口形态为：

```go
type ProjectAnnotationParser interface {
    ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*ParseProjectAnnotationsResult, error)
}
```

其中：

`ParseProjectAnnotationsRequest`
- `FormatProfile`
- `RootDir`
- `Strict`
- `GeometryPolicy`
- `PathPolicy`

`ParseProjectAnnotationsResult`
- `Batch *annotationirv1.DataBatchIR`
- `SampleRefs []SampleRef`
- `Report ConversionReport`
- `DetectedGeometryKinds []string`
- `UnsupportedGeometryKinds []string`

核心要求：

- `Batch` 保持 IR 语义纯净
- `SampleRefs` 负责保留外部样本引用信息
- `Report` 用于 prepare 阶段构建 warnings / errors
- 几何能力统计用于 capability 判定

### 5.5 为什么不能只返回 `DataBatchIR`

仅返回 `DataBatchIR` 不足以支撑 import prepare，因为 prepare 还需要：

- 原始 sample key
- 原始几何输入类型
- 转换 warning / error
- 哪些 geometry 被降级、拟合或阻断

这些信息不应污染 `IR Core proto`，因此必须通过 adapter result 单独承载。

## 6. Importing 模块边界

`saki-controlplane/internal/modules/importing` 的职责应收敛为：

- upload session
- prepare
- execute
- task / result / event stream
- sample matching
- label planning
- manifest 管理

它不负责：

- 解析 COCO JSON 细节
- 解析 YOLO txt / yaml 细节
- 处理 poly8 拟合算法

这些都由 `saki-ir/go` adapter 完成。

## 7. Project Annotation Import 工作流

### 7.1 保留的交互模型

第一阶段继续保留旧系统的四段模型：

1. `upload session`
2. `prepare`
3. `execute`
4. `import task + result + events`

这套模型比同步一次性导入更适合长期演进，因为：

- 可以支持 preview
- 可以支持确认型执行
- 可以支持事件流
- 可与前端 import workspace 对齐

### 7.2 Upload Session

`upload session` 仅负责让导入源文件进入系统，并形成稳定引用。

它不负责：

- 格式解析
- project/dataset/sample 校验
- dry-run 结果生成

### 7.3 Prepare

`prepare` 是纯 dry-run 阶段，负责：

- 读取上传归档
- 调 `Go-native adapter`
- 样本匹配
- label 规划
- geometry capability 检查
- 生成 warnings / errors
- 生成 `preview token + manifest`

`prepare` 不应写 annotation、label 或 sample。

### 7.4 Execute

`execute` 只负责：

- 校验 `preview_token`
- 校验 manifest 未漂移
- 校验是否允许执行
- 创建 import task
- 异步执行实际落库

`execute` 不应重新承担完整格式解析决策。

### 7.5 Import Task

第一阶段保留：

- task status
- result
- events

至少支持：

- `queued`
- `running`
- `succeeded`
- `failed`

并保留事件类型：

- `start`
- `phase`
- `warning`
- `error`
- `complete`

## 8. 样本匹配策略

### 8.1 主精确匹配键

第一阶段的主精确匹配键是：

- `dataset_relpath`

次级兼容键：

- `sample_name`

未来预留：

- `external_ref`
- `asset hash`

### 8.2 为什么以 `dataset_relpath` 为主

相较于 basename，`dataset_relpath` 有更强唯一性，并且更贴近：

- COCO 的 `images[].file_name`
- YOLO 的图像相对路径语义

这里提取目录结构，不是为了保留“压缩包目录树”，而是为了得到稳定的逻辑相对路径引用键。

### 8.3 匹配策略

第一阶段匹配策略：

1. 先按 `dataset_relpath` 精确匹配
2. 再按 `sample_name` 精确匹配
3. 精确匹配失败后，允许 `basename fallback`

`basename fallback` 规则必须严格：

- 仅在精确匹配失败后触发
- 仅允许唯一命中
- 命中必须记录 warning
- 多命中必须报错，不允许猜测

### 8.4 Match Ref 持久化

长期建议在控制面中显式持久化样本匹配引用，而不是只依赖 `sample.meta`。

推荐新增：

- `sample_match_ref`

字段建议：

- `id`
- `sample_id`
- `dataset_id`
- `ref_type`
- `ref_value`
- `is_primary`
- `created_at`

第一阶段可以仍以现有 sample 数据组织方式过渡，但设计上必须预留这张表。

## 9. Prepare / Manifest / Execute 数据模型

### 9.1 Prepare Result

`prepare` 返回结果至少应包含：

`summary`
- `format_profile`
- `total_annotations`
- `matched_annotations`
- `unmatched_annotations`
- `matched_samples`
- `unsupported_annotations`

`issues`
- `warnings`
- `errors`

`matching`
- `matched_sample_count`
- `basename_fallback_count`
- `ambiguous_match_count`
- `unmatched_sample_keys`

`label_plan`
- `planned_new_labels`

`geometry_capabilities`
- `detected_geometry_kinds`
- `unsupported_geometry_kinds`
- `converted_geometry_counts`

以及：
- `preview_token`

### 9.2 Preview Token 与 Manifest

`execute` 不应让客户端重新提交整份 prepare 结果，因此需要：

- `preview_token`
- 服务端 manifest

manifest 应存“执行所需的最小充分信息”，例如：

- `mode`
- `project_id`
- `dataset_id`
- `branch_name`
- `format_profile`
- `upload_session_id` 或 archive 引用
- 已解析且匹配完成的 annotation entries
- `planned_new_labels`
- `summary`
- `warnings`
- `errors`
- `params_hash`

### 9.3 Execute 阻断策略

第一阶段执行策略：

- `prepare` 中存在 blocking errors 时，`execute` 直接拒绝
- mixed supported/unsupported 内容时，默认整批阻断
- `execute` 不做部分成功
- `execute` 成功语义为整批成功

## 10. Geometry Capability Matrix

本阶段设计中明确引入 geometry capability matrix：

- `COCO bbox` -> `rect` -> `IR.rect`
- `YOLO det txt` -> `rect` -> `IR.rect`
- `YOLO OBB xywhr` -> `obb_xywhr` -> `IR.obb`（设计预留）
- `YOLO OBB poly8` -> `obb_poly8` -> `IR.obb`（设计预留）
- `DOTA poly8` -> `obb_poly8` -> `IR.obb`（设计预留）

要求：

- `prepare` 必须明确告知检测到的 geometry kinds
- `prepare` 必须区分“已支持”“未支持”“已转换”
- `execute` 必须根据 capability 结果决定是否允许执行

## 11. 测试策略

建议拆成四层：

1. `saki-ir/go` adapter 单元测试
   - `COCO bbox -> IR rect`
   - `YOLO det txt -> IR rect`
   - geometry capability 统计
2. import matching 单元测试
   - `dataset_relpath`
   - `sample_name`
   - basename fallback
   - ambiguous cases
3. controlplane prepare/execute API 测试
   - upload -> prepare -> execute -> task
4. smoke 测试
   - 走最小 project annotation import 闭环

## 12. 非目标

本阶段不做：

- 通用 Python import engine
- 完整 COCO 任务族支持
- 完整 YOLO OBB 实现
- `VOC / DOTA` 真正迁入 Go
- import/export 全部恢复
- 复杂部分成功 / 补偿工作流

## 13. 演进顺序

建议按两段推进：

### 阶段 A：Go-native IR Adapters

在 `shared/saki-ir/go` 中补齐：

- `COCO bbox -> IR rect`
- `YOLO det txt -> IR rect`
- adapter result / conversion report / geometry capability

### 阶段 B：Project Annotation Import

在 `saki-controlplane/internal/modules/importing` 中补齐：

- upload session
- prepare
- manifest / preview token
- execute
- import task / result / events
- sample matching / label planning

## 14. 最终建议

最终建议是：

- 继续保留并强化 `IR Core`
- 把 `COCO / YOLO` adapters 迁入 `Go-native saki-ir`
- controlplane 只做 import orchestration
- 复杂算法或特殊格式能力只在真正必要时才留在 Python

这样既能保留 `IR` 的跨语言价值，又能避免新控制面长期依赖 Python 导入子系统。
