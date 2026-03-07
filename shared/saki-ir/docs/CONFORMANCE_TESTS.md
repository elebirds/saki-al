# Saki IR v1 一致性测试清单（CONFORMANCE TESTS）

> 目标：任何实现只要通过以下条目，即可认为在 v1 关键语义上与参考实现一致。

## 必须通过

- [x] **Test name**: OBB normalize golden cases
  - **Spec reference**: `IR_SPEC.md#6-obb-normalization`
  - **What to assert**: `width < height` 时触发 swap + `angle += 90`，最终角度落在 `[-180,180)` 且 `180 -> -180`。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_obb_normalize_golden_cases`
    - Go: `go/sakir/normalize_test.go::TestNormalizeOBBGoldenCases`

- [x] **Test name**: Rect invalid cases
  - **Spec reference**: `IR_SPEC.md#4-rect-semantics`, `IR_SPEC.md#8-invalid-values`
  - **What to assert**: `width<=EPS`、`height<=EPS`、`NaN/Inf` 必须失败并归类几何错误。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_rect_invalid_cases`
    - Go: `go/sakir/normalize_test.go::TestRectInvalidCases`

- [x] **Test name**: Confidence invalid cases
  - **Spec reference**: `IR_SPEC.md#8-invalid-values`, `IR_SPEC.md#11-error-code-contract`
  - **What to assert**: `confidence` 非有限值或不在 `[0,1]` 必须失败并归类 schema 错误。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_confidence_invalid`
    - Go: `go/sakir/normalize_test.go::TestConfidenceInvalidCases`

- [x] **Test name**: Validate no in-place mutation
  - **Spec reference**: `IR_SPEC.md#8-invalid-values`（Validate 语义约束）
  - **What to assert**: `Validate` 不修改输入对象。
  - **Where implemented**:
    - Go: `go/sakir/normalize_test.go::TestValidateDoesNotModifyInput`

- [x] **Test name**: Encode/Decode round-trip with NONE
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`
  - **What to assert**: 在 `compression=NONE` 下往返后语义一致。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_encode_decode_roundtrip_none`
    - Go: `go/sakir/codec_test.go::TestEncodeDecodeRoundTripNone`

- [x] **Test name**: Encode/Decode round-trip with ZSTD
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`
  - **What to assert**: 大 payload 触发 ZSTD，解码后条目数一致。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_encode_decode_roundtrip_zstd`
    - Go: `go/sakir/codec_test.go::TestEncodeDecodeRoundTripZSTD`

- [x] **Test name**: Encode parameter bounds
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`
  - **What to assert**: level 越界报 schema 错误；`level=0` 应映射到默认值。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_encode_parameter_normalization_and_bounds`
    - Go: `go/sakir/codec_test.go::TestEncodeLevelBounds`

- [x] **Test name**: Checksum mismatch detection
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`, `IR_SPEC.md#11-error-code-contract`
  - **What to assert**: 篡改 `payload` 或 `header.checksum` 后解码失败并返回 checksum mismatch。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_checksum_mismatch`
    - Go: `go/sakir/codec_test.go::TestChecksumMismatch`

- [x] **Test name**: Header-only read without decode
  - **Spec reference**: `IR_SPEC.md#10-header-only-behavior`
  - **What to assert**: 读取 header 不需要解压/解码。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_read_header_without_zstd_dependency_on_none`
    - Go: `go/sakir/codec_test.go::TestReadHeaderNoDecode`

- [x] **Test name**: CRC32C standard vector
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`
  - **What to assert**: `CRC32C("123456789") == 0xE3069283`。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_crc32c_standard_vector`
    - Go: `go/sakir/codec_test.go::TestCRC32CStandardVector`

- [x] **Test name**: Cross-language CRC32C vector
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`
  - **What to assert**: 对同一字节序列，Python/Go CRC32C 结果一致（用于 encoded payload 校验实现一致性）。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_cross_language_crc32c_vector`
    - Go: `go/sakir/codec_test.go::TestCrossLanguageCRC32CVector`

- [x] **Test name**: OBB vertices invariant under normalization
  - **Spec reference**: `IR_SPEC.md#6-obb-normalization`, `IR_SPEC.md#7-vertices-and-aabb`
  - **What to assert**: normalize 前后顶点集合一致（允许顺序变化）。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_obb_vertices_invariant_after_normalize`
    - Go: `go/sakir/normalize_test.go::TestOBBVerticesInvariantAfterNormalize`

- [x] **Test name**: OBB zero-angle direction
  - **Spec reference**: `IR_SPEC.md#5-obb-semantics`, `IR_SPEC.md#7-vertices-and-aabb`
  - **What to assert**: `angle=0` 时 width 边方向与 +x 一致。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_obb_vertices_direction_zero_angle`
    - Go: `go/sakir/normalize_test.go::TestOBBVerticesDirectionForZeroAngle`

- [x] **Test name**: OBB positive-90 direction in screen-CCW
  - **Spec reference**: `IR_SPEC.md#5-obb-semantics`, `IR_SPEC.md#7-vertices-and-aabb`
  - **What to assert**: `angle=+90` 时 local width 边方向朝 `+y`（向下）。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_obb_vertices_direction_positive_90_ccw`
    - Go: `go/sakir/normalize_test.go::TestOBBVerticesDirectionForPositive90CCW`

- [x] **Test name**: OBB screen-sorted vertices order
  - **Spec reference**: `IR_SPEC.md#7-vertices-and-aabb`
  - **What to assert**: screen 顶点顺序稳定为 `TL,TR,BR,BL`，满足上方点在前、左侧点在前。
  - **Where implemented**:
    - Python: `python/tests/test_ir.py::test_obb_vertices_screen_order`
    - Go: `go/sakir/normalize_test.go::TestOBBVerticesScreenOrder`

- [x] **Test name**: View verify checksum does not decode
  - **Spec reference**: `IR_SPEC.md#10-header-only-behavior`, `IR_SPEC.md#13-view-wrapper-guidance`
  - **What to assert**: `verify_checksum` 仅解压+校验，不触发 protobuf parse。
  - **Where implemented**:
    - Python: `python/tests/test_view.py::test_view_verify_checksum_does_not_decode`
    - Go: `go/sakir/view_test.go::TestEncodedPayloadViewVerifyChecksumNoDecode`

- [x] **Test name**: GeometryView AABB covers vertices
  - **Spec reference**: `IR_SPEC.md#7-vertices-and-aabb`
  - **What to assert**: AABB 等于顶点 min/max 包围盒。
  - **Where implemented**:
    - Python: `python/tests/test_view.py::test_geometry_view_vertices_and_aabb`
    - Go: `go/sakir/view_test.go::TestGeometryViewAABBCoversVertices`

- [x] **Test name**: BatchView normalized_copy no in-place
  - **Spec reference**: `IR_SPEC.md#13-view-wrapper-guidance`
  - **What to assert**: `normalized_copy()` 不修改原 batch，返回规范化副本。
  - **Where implemented**:
    - Python: `python/tests/test_view.py::test_batch_view_normalized_copy_no_inplace`

- [x] **Test name**: decode(normalize_output) switch behavior
  - **Spec reference**: `IR_SPEC.md#9-encoded-payload`
  - **What to assert**: `normalize_output=False` 保留原始几何，`True` 输出规范化几何。
  - **Where implemented**:
    - Python: `python/tests/test_view.py::test_encoded_payload_view_decode_without_normalize`

## 备注
- 本清单以当前参考实现与现有测试为事实基准。
- 若新增语言实现，需至少覆盖上述同等断言。
