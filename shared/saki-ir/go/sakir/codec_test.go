package sakir

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/proto"
)

type crc32cVector struct {
	PayloadRawHex  string `json:"payload_raw_hex"`
	ExpectedCRC32C uint32 `json:"expected_crc32c"`
}

func TestEncodeDecodeRoundTripNone(t *testing.T) {
	batch := makeSmallBatch()

	encoded, err := Encode(batch, 1_000_000, 3)
	if err != nil {
		t.Fatalf("Encode failed: %v", err)
	}
	if got, want := encoded.GetHeader().GetCompression(), annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_NONE; got != want {
		t.Fatalf("compression got %v want %v", got, want)
	}

	decoded, err := Decode(encoded)
	if err != nil {
		t.Fatalf("Decode failed: %v", err)
	}

	expected := proto.Clone(batch).(*annotationirv1.DataBatchIR)
	if err := Normalize(expected); err != nil {
		t.Fatalf("Normalize expected failed: %v", err)
	}
	if !proto.Equal(decoded, expected) {
		t.Fatalf("decoded batch mismatch")
	}
}

func TestEncodeDecodeRoundTripZSTD(t *testing.T) {
	items := make([]*annotationirv1.DataItemIR, 0, 5001)
	items = append(items, &annotationirv1.DataItemIR{
		Item: &annotationirv1.DataItemIR_Label{
			Label: &annotationirv1.LabelRecord{Id: "label-1", Name: "car", Color: "#ff0000"},
		},
	})
	for i := 0; i < 5000; i++ {
		items = append(items, &annotationirv1.DataItemIR{
			Item: &annotationirv1.DataItemIR_Annotation{
				Annotation: &annotationirv1.AnnotationRecord{
					Id:         "ann-zstd",
					SampleId:   "sample-1",
					LabelId:    "label-1",
					Source:     annotationirv1.AnnotationSource_ANNOTATION_SOURCE_MODEL,
					Confidence: 0.6,
					Geometry: &annotationirv1.Geometry{
						Shape: &annotationirv1.Geometry_Rect{
							Rect: &annotationirv1.RectGeometry{X: float32(i), Y: 2, Width: 100, Height: 20},
						},
					},
				},
			},
		})
	}
	batch := &annotationirv1.DataBatchIR{Items: items}

	encoded, err := Encode(batch, 32768, 3)
	if err != nil {
		t.Fatalf("Encode failed: %v", err)
	}
	if got, want := encoded.GetHeader().GetCompression(), annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_ZSTD; got != want {
		t.Fatalf("compression got %v want %v", got, want)
	}

	decoded, err := Decode(encoded)
	if err != nil {
		t.Fatalf("Decode failed: %v", err)
	}
	if got, want := len(decoded.GetItems()), len(batch.GetItems()); got != want {
		t.Fatalf("decoded item count got %d want %d", got, want)
	}
}

func TestChecksumMismatch(t *testing.T) {
	encoded, err := Encode(makeSmallBatch(), 1_000_000, 3)
	if err != nil {
		t.Fatalf("Encode failed: %v", err)
	}
	encoded.Header.Checksum++

	_, err = Decode(encoded)
	assertErrCode(t, err, ErrIRChecksumMismatch)
}

func TestReadHeaderNoDecode(t *testing.T) {
	encoded, err := Encode(makeSmallBatch(), 1_000_000, 3)
	if err != nil {
		t.Fatalf("Encode failed: %v", err)
	}
	header := ReadHeader(encoded)
	if header == nil {
		t.Fatal("header is nil")
	}
	if got, want := header.GetSchema(), annotationirv1.PayloadSchema_PAYLOAD_SCHEMA_DATA_BATCH_IR; got != want {
		t.Fatalf("schema got %v want %v", got, want)
	}
}

func TestEncodeLevelBounds(t *testing.T) {
	_, err := Encode(makeSmallBatch(), 1024, 23)
	assertErrCode(t, err, ErrIRSchema)
	_, err = Encode(makeSmallBatch(), 1024, -1)
	assertErrCode(t, err, ErrIRSchema)
}

func TestCRC32CStandardVector(t *testing.T) {
	if got, want := checksumCRC32C([]byte("123456789")), uint32(0xE3069283); got != want {
		t.Fatalf("checksum got %#x want %#x", got, want)
	}
}

func TestCrossLanguageCRC32CVector(t *testing.T) {
	vectorPath := "../../testdata/crc32c_vector.json"
	content, err := os.ReadFile(vectorPath)
	if err != nil {
		t.Fatalf("read vector file failed: %v", err)
	}
	var vec crc32cVector
	if err := json.Unmarshal(content, &vec); err != nil {
		t.Fatalf("unmarshal vector failed: %v", err)
	}
	payloadRaw, err := hex.DecodeString(vec.PayloadRawHex)
	if err != nil {
		t.Fatalf("decode hex failed: %v", err)
	}
	if got := checksumCRC32C(payloadRaw); got != vec.ExpectedCRC32C {
		t.Fatalf("checksum got %#x want %#x", got, vec.ExpectedCRC32C)
	}
}

func makeSmallBatch() *annotationirv1.DataBatchIR {
	return &annotationirv1.DataBatchIR{
		Items: []*annotationirv1.DataItemIR{
			{
				Item: &annotationirv1.DataItemIR_Label{
					Label: &annotationirv1.LabelRecord{Id: "label-1", Name: "car", Color: "#ff0000"},
				},
			},
			{
				Item: &annotationirv1.DataItemIR_Sample{
					Sample: &annotationirv1.SampleRecord{Id: "sample-1", AssetHash: "hash-1", Width: 1920, Height: 1080},
				},
			},
			{
				Item: &annotationirv1.DataItemIR_Annotation{
					Annotation: &annotationirv1.AnnotationRecord{
						Id:         "ann-1",
						SampleId:   "sample-1",
						LabelId:    "label-1",
						Source:     annotationirv1.AnnotationSource_ANNOTATION_SOURCE_MANUAL,
						Confidence: 0.9,
						Geometry: &annotationirv1.Geometry{
							Shape: &annotationirv1.Geometry_Rect{
								Rect: &annotationirv1.RectGeometry{X: 10, Y: 20, Width: 100, Height: 40},
							},
						},
					},
				},
			},
		},
	}
}
