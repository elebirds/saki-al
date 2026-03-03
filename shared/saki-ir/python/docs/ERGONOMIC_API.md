# saki-ir Ergonomic API

## 推荐调用层级
1. `saki_ir.api`（默认，业务场景首选）
2. `saki_ir.normalize_ir / validate_ir`（高级批处理）
3. 直接 protobuf 读写（底层，不推荐业务侧直接使用）

## Geometry Facade
```python
from saki_ir import normalize_geometry_payload, parse_geometry
```

- `normalize_geometry_payload(payload)`：输入 `{"rect":...}` / `{"obb":...}`，返回规范化后的 payload。
- `parse_geometry(payload)`：返回 `irpb.Geometry`。
- `validate_geometry_payload(payload)`：仅校验，不返回值。
- 失败统一抛 `IRValidationError`，包含 `code/path/hint/message`。

## Prediction Facade
```python
from saki_ir import normalize_prediction_candidates
```

- 统一入口：`normalize_prediction_candidates(candidates)`。
- 单条入口：`normalize_prediction_candidate(candidate)`、`normalize_prediction_snapshot(snapshot)`、`normalize_prediction_entry(entry)`。
- prediction entry 仅允许：
  - `class_index`（必填）
  - `class_name`（可选）
  - `confidence`（必填）
  - `geometry`（必填，rect/obb）
  - `label_id`（可选）
  - `attrs`（可选）
- legacy 字段（如 `cls_id/conf/xyxy/predictionSnapshot`）会直接失败。

## 错误处理
```python
from saki_ir import IRValidationError

try:
    normalize_prediction_candidates(candidates)
except IRValidationError as exc:
    print(exc.to_message())
    print(exc.to_dict())
```

- `to_message()`：适合日志直出。
- `to_dict()`：适合 API 返回结构化错误。
