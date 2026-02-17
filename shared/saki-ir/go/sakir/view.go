package sakir

import (
	"math"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/proto"
)

type EncodedPayloadView struct {
	Encoded *annotationirv1.EncodedPayload
}

func (v EncodedPayloadView) Header() *annotationirv1.PayloadHeader {
	return v.HeaderRef()
}

// HeaderRef 返回 header 引用，不做拷贝。
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

func (v EncodedPayloadView) Stats() *annotationirv1.PayloadStats {
	header := v.Header()
	if header == nil || header.GetStats() == nil {
		return &annotationirv1.PayloadStats{}
	}
	return header.GetStats()
}

func (v EncodedPayloadView) DecompressRaw() ([]byte, error) {
	if v.Encoded == nil {
		return nil, newError(ErrIRSchema, "encoded payload is nil")
	}
	header := v.Header()
	if header == nil {
		return nil, newError(ErrIRSchema, "header is missing")
	}
	return decodeCompression(header.GetCompression(), v.Encoded.GetPayload())
}

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
	raw, err := v.DecompressRaw()
	if err != nil {
		return err
	}
	actual := checksumCRC32C(raw)
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

func (v EncodedPayloadView) Decode() (*annotationirv1.DataBatchIR, error) {
	return Decode(v.Encoded)
}

type BatchView struct {
	Batch *annotationirv1.DataBatchIR
}

func (v BatchView) IterItems() []*annotationirv1.DataItemIR {
	if v.Batch == nil {
		return nil
	}
	return v.Batch.GetItems()
}

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

type GeometryView struct {
	G *annotationirv1.Geometry
}

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

func (v GeometryView) Vertices() ([4]Point, error) {
	if v.G == nil || v.G.GetShape() == nil {
		return [4]Point{}, newError(ErrIRGeometry, "geometry.shape is missing")
	}
	switch shape := v.G.GetShape().(type) {
	case *annotationirv1.Geometry_Rect:
		return RectToVertices(shape.Rect), nil
	case *annotationirv1.Geometry_Obb:
		return ObbToVertices(shape.Obb), nil
	default:
		return [4]Point{}, newError(ErrIRGeometry, "geometry.shape is missing")
	}
}

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
