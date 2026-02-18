package sakir

import (
	"math"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/proto"
)

// EncodedPayloadView 是 EncodedPayload 的只读便利视图。
//
// 设计目标：
// - Header/Stats 支持 header-only 读取
// - VerifyChecksum 可独立执行，不需要 decode
// - 默认无副作用
type EncodedPayloadView struct {
	// Encoded 是被包裹的 protobuf 消息。
	Encoded *annotationirv1.EncodedPayload
}

// Header 返回 header 引用，等价于 HeaderRef。
func (v EncodedPayloadView) Header() *annotationirv1.PayloadHeader {
	return v.HeaderRef()
}

// HeaderRef 返回 header 引用，不做拷贝。
//
// Spec: docs/IR_SPEC.md#10-header-only-behavior
func (v EncodedPayloadView) HeaderRef() *annotationirv1.PayloadHeader {
	return ReadHeader(v.Encoded)
}

// HeaderCopy 返回 header 深拷贝，供需要隔离修改的调用方使用。
func (v EncodedPayloadView) HeaderCopy() *annotationirv1.PayloadHeader {
	header := v.HeaderRef()
	if header == nil {
		return nil
	}
	copied, ok := proto.Clone(header).(*annotationirv1.PayloadHeader)
	if !ok {
		return nil
	}
	return copied
}

// Stats 返回 stats 引用；若 header/stats 缺失则返回空 stats 对象。
func (v EncodedPayloadView) Stats() *annotationirv1.PayloadStats {
	header := v.Header()
	if header == nil || header.GetStats() == nil {
		return &annotationirv1.PayloadStats{}
	}
	return header.GetStats()
}

// DecompressRaw 只处理压缩层，返回未压缩 payloadRaw。
//
// 不做 checksum 校验，不做 protobuf decode。
//
// Spec: docs/IR_SPEC.md#9-encoded-payload
// Spec: docs/IR_SPEC.md#10-header-only-behavior
func (v EncodedPayloadView) DecompressRaw() ([]byte, error) {
	if v.Encoded == nil {
		return nil, newError(ErrIRSchema, "encoded payload is nil")
	}
	header := v.Header()
	if header == nil {
		return nil, newError(ErrIRSchema, "header is missing")
	}
	return decodeCompression(header.GetCompression(), v.Encoded.GetPayload(), defaultMaxUncompressedSize)
}

// VerifyChecksum 只校验 checksum，不执行解压与 decode。
//
// Spec: docs/IR_SPEC.md#10-header-only-behavior
func (v EncodedPayloadView) VerifyChecksum() error {
	if v.Encoded == nil {
		return newError(ErrIRSchema, "encoded payload is nil")
	}
	header := v.Header()
	if header == nil {
		return newError(ErrIRSchema, "header is missing")
	}
	if header.GetChecksumAlgo() != annotationirv1.PayloadChecksumAlgo_PAYLOAD_CHECKSUM_ALGO_CRC32C {
		return newError(ErrIRSchema, "unsupported checksum algo: %v", header.GetChecksumAlgo())
	}
	actual := checksumCRC32C(v.Encoded.GetPayload())
	if actual != header.GetChecksum() {
		return newError(
			ErrIRChecksumMismatch,
			"checksum mismatch: expected=%d actual=%d",
			header.GetChecksum(),
			actual,
		)
	}
	return nil
}

// Decode 调用包级 Decode，返回 DataBatchIR。
func (v EncodedPayloadView) Decode() (*annotationirv1.DataBatchIR, error) {
	return Decode(v.Encoded)
}

// BatchView 是 DataBatchIR 的轻量只读视图。
type BatchView struct {
	// Batch 是被包裹的 protobuf 消息。
	Batch *annotationirv1.DataBatchIR
}

// IterItems 返回底层 items 切片（nil-safe）。
func (v BatchView) IterItems() []*annotationirv1.DataItemIR {
	if v.Batch == nil {
		return nil
	}
	return v.Batch.GetItems()
}

// Counts 返回 item/annotation/sample/label 计数，口径与 payload stats 一致。
func (v BatchView) Counts() (item, ann, sample, label uint32) {
	if v.Batch == nil {
		return 0, 0, 0, 0
	}
	item = uint32(len(v.Batch.GetItems()))
	for _, it := range v.Batch.GetItems() {
		switch {
		case it.GetAnnotation() != nil:
			ann++
		case it.GetSample() != nil:
			sample++
		case it.GetLabel() != nil:
			label++
		}
	}
	return item, ann, sample, label
}

// GeometryView 是 Geometry 的只读计算视图。
type GeometryView struct {
	// G 是被包裹的 protobuf 消息。
	G *annotationirv1.Geometry
}

// Kind 返回 shape 类型：rect / obb / ""。
func (v GeometryView) Kind() string {
	if v.G == nil {
		return ""
	}
	switch v.G.GetShape().(type) {
	case *annotationirv1.Geometry_Rect:
		return "rect"
	case *annotationirv1.Geometry_Obb:
		return "obb"
	default:
		return ""
	}
}

// Vertices 返回 4 个顶点。
//
// 顺序固定为 TL, TR, BR, BL。对于 OBB，这是局部角点顺序（local corner order），
// 不是按屏幕坐标排序后的角点顺序。
//
// Spec: docs/IR_SPEC.md#7-vertices-and-aabb
func (v GeometryView) Vertices() ([4]Point, error) {
	if v.G == nil || v.G.GetShape() == nil {
		return [4]Point{}, newError(ErrIRGeometry, "geometry.shape is missing")
	}
	switch shape := v.G.GetShape().(type) {
	case *annotationirv1.Geometry_Rect:
		return RectToVerticesScreen(shape.Rect), nil
	case *annotationirv1.Geometry_Obb:
		return ObbToVerticesLocal(shape.Obb), nil
	default:
		return [4]Point{}, newError(ErrIRGeometry, "geometry.shape is missing")
	}
}

// AABBRectTL 返回由顶点 min/max 计算得到的 axis-aligned rect (x, y, w, h)。
//
// Spec: docs/IR_SPEC.md#7-vertices-and-aabb
func (v GeometryView) AABBRectTL() (x, y, w, h float32, err error) {
	vertices, err := v.Vertices()
	if err != nil {
		return 0, 0, 0, 0, err
	}

	minX := float64(vertices[0].X)
	minY := float64(vertices[0].Y)
	maxX := minX
	maxY := minY
	for i := 1; i < 4; i++ {
		vx := float64(vertices[i].X)
		vy := float64(vertices[i].Y)
		minX = math.Min(minX, vx)
		minY = math.Min(minY, vy)
		maxX = math.Max(maxX, vx)
		maxY = math.Max(maxY, vy)
	}

	return float32(minX), float32(minY), float32(maxX - minX), float32(maxY - minY), nil
}
