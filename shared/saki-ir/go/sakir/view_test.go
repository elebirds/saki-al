package sakir

import (
	"errors"
	"testing"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

func TestEncodedPayloadViewHeaderStatsNilSafe(t *testing.T) {
	var nilView EncodedPayloadView
	if nilView.Header() != nil {
		t.Fatalf("expected nil header for nil payload")
	}
	stats := nilView.Stats()
	if stats == nil {
		t.Fatal("expected non-nil empty stats")
	}
	if stats.GetItemCount() != 0 {
		t.Fatalf("expected empty stats item_count=0, got %d", stats.GetItemCount())
	}
}

func TestEncodedPayloadViewVerifyChecksumNoDecode(t *testing.T) {
	raw := []byte{0x10, 0x20, 0x30, 0x40, 0x50}
	header := &annotationirv1.PayloadHeader{
		Schema:        annotationirv1.PayloadSchema_PAYLOAD_SCHEMA_DATA_BATCH_IR,
		SchemaVersion: 1,
		Codec:         annotationirv1.PayloadCodec_PAYLOAD_CODEC_MSGPACK,
		Compression:   annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_NONE,
		ChecksumAlgo:  annotationirv1.PayloadChecksumAlgo_PAYLOAD_CHECKSUM_ALGO_CRC32C,
		Checksum:      checksumCRC32C(raw),
	}
	encoded := &annotationirv1.EncodedPayload{Header: header, Payload: raw}
	view := EncodedPayloadView{Encoded: encoded}

	if err := view.VerifyChecksum(); err != nil {
		t.Fatalf("VerifyChecksum should pass without decode: %v", err)
	}

	encoded.Header.Checksum++
	err := view.VerifyChecksum()
	var irErr *Error
	if !errors.As(err, &irErr) {
		t.Fatalf("expected *Error, got %T (%v)", err, err)
	}
	if irErr.Code != ErrIRChecksumMismatch {
		t.Fatalf("expected checksum mismatch error, got %s", irErr.Code)
	}
}

func TestGeometryViewAABBCoversVertices(t *testing.T) {
	gv := GeometryView{
		G: &annotationirv1.Geometry{
			Shape: &annotationirv1.Geometry_Obb{
				Obb: &annotationirv1.ObbGeometry{
					Cx:         100,
					Cy:         50,
					Width:      6,
					Height:     2,
					AngleDegCw: 30,
				},
			},
		},
	}
	vertices, err := gv.Vertices()
	if err != nil {
		t.Fatalf("Vertices failed: %v", err)
	}
	x, y, w, h, err := gv.AABBRectTL()
	if err != nil {
		t.Fatalf("AABBRectTL failed: %v", err)
	}

	minX, minY := float64(vertices[0].X), float64(vertices[0].Y)
	maxX, maxY := minX, minY
	for i := 1; i < 4; i++ {
		minX = minf(minX, float64(vertices[i].X))
		minY = minf(minY, float64(vertices[i].Y))
		maxX = maxf(maxX, float64(vertices[i].X))
		maxY = maxf(maxY, float64(vertices[i].Y))
	}

	assertClose(t, float64(x), minX, 1e-5)
	assertClose(t, float64(y), minY, 1e-5)
	assertClose(t, float64(x+w), maxX, 1e-5)
	assertClose(t, float64(y+h), maxY, 1e-5)
}

func minf(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func maxf(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

func assertClose(t *testing.T, got, want, tol float64) {
	t.Helper()
	diff := got - want
	if diff < 0 {
		diff = -diff
	}
	if diff > tol {
		t.Fatalf("got %.9f, want %.9f (tol=%.9f)", got, want, tol)
	}
}
