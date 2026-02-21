package sakir

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	manifestirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/manifestirv1"
)

type selectorVector struct {
	Name        string     `json:"name"`
	SnapshotID  string     `json:"snapshot_id"`
	Encoding    string     `json:"encoding"`
	Ranges      [][]uint32 `json:"ranges"`
	BitsetHex   string     `json:"bitset_le_hex"`
	RoaringHex  string     `json:"roaring_hex"`
	Cardinality uint32     `json:"cardinality"`
	Checksum    string     `json:"checksum"`
}

type selectorVectorFile struct {
	Cases []selectorVector `json:"cases"`
}

func loadSelectorVectors(t *testing.T) []selectorVector {
	t.Helper()
	vectorPath := filepath.Join("..", "..", "testdata", "selector_vector.json")
	raw, err := os.ReadFile(vectorPath)
	if err != nil {
		t.Fatalf("read selector vector file: %v", err)
	}
	payload := selectorVectorFile{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatalf("parse selector vector file: %v", err)
	}
	return payload.Cases
}

func buildSelector(t *testing.T, vector selectorVector) *manifestirv1.ManifestSelector {
	t.Helper()
	selector := &manifestirv1.ManifestSelector{
		SnapshotId:  vector.SnapshotID,
		Cardinality: vector.Cardinality,
		Checksum:    vector.Checksum,
	}
	switch vector.Encoding {
	case "RANGE":
		selector.Encoding = manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_RANGE
		ranges := &manifestirv1.RangeSelector{}
		for _, pair := range vector.Ranges {
			if len(pair) != 2 {
				t.Fatalf("invalid range pair: %#v", pair)
			}
			ranges.Ranges = append(ranges.Ranges, &manifestirv1.OrdinalRange{Start: pair[0], End: pair[1]})
		}
		selector.Payload = &manifestirv1.ManifestSelector_Range{Range: ranges}
	case "BITSET":
		selector.Encoding = manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_BITSET
		raw, err := hex.DecodeString(vector.BitsetHex)
		if err != nil {
			t.Fatalf("decode bitset hex: %v", err)
		}
		selector.Payload = &manifestirv1.ManifestSelector_Bitset{
			Bitset: &manifestirv1.BitsetSelector{BitsetLe: raw},
		}
	case "ROARING":
		selector.Encoding = manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_ROARING
		raw, err := hex.DecodeString(vector.RoaringHex)
		if err != nil {
			t.Fatalf("decode roaring hex: %v", err)
		}
		selector.Payload = &manifestirv1.ManifestSelector_Roaring{
			Roaring: &manifestirv1.RoaringSelector{Bitmap: raw},
		}
	default:
		t.Fatalf("unsupported selector encoding: %s", vector.Encoding)
	}
	return selector
}

func TestSelectorVectorCardinalityAndChecksum(t *testing.T) {
	for _, vector := range loadSelectorVectors(t) {
		t.Run(vector.Name, func(t *testing.T) {
			selector := buildSelector(t, vector)
			cardinality, err := SelectorCardinality(selector)
			if err != nil {
				t.Fatalf("SelectorCardinality failed: %v", err)
			}
			if cardinality != vector.Cardinality {
				t.Fatalf("cardinality mismatch expected=%d actual=%d", vector.Cardinality, cardinality)
			}

			checksum, err := SelectorChecksum(selector)
			if err != nil {
				t.Fatalf("SelectorChecksum failed: %v", err)
			}
			if checksum != vector.Checksum {
				t.Fatalf("checksum mismatch expected=%s actual=%s", vector.Checksum, checksum)
			}

			validatedCardinality, validatedChecksum, err := ValidateManifestSelector(selector)
			if err != nil {
				t.Fatalf("ValidateManifestSelector failed: %v", err)
			}
			if validatedCardinality != vector.Cardinality {
				t.Fatalf("validated cardinality mismatch expected=%d actual=%d", vector.Cardinality, validatedCardinality)
			}
			if validatedChecksum != vector.Checksum {
				t.Fatalf("validated checksum mismatch expected=%s actual=%s", vector.Checksum, validatedChecksum)
			}
		})
	}
}

func TestValidateManifestSelectorChecksumMismatch(t *testing.T) {
	vectors := loadSelectorVectors(t)
	if len(vectors) == 0 {
		t.Fatal("no selector vectors found")
	}
	selector := buildSelector(t, vectors[0])
	selector.Checksum = "deadbeef"
	if _, _, err := ValidateManifestSelector(selector); err == nil {
		t.Fatal("expected checksum mismatch error")
	}
}
