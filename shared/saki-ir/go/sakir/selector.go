package sakir

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"math/bits"
	"sort"

	manifestirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/manifestirv1"
)

const maxUint32Value = uint64(^uint32(0))

func normalizeRanges(selector *manifestirv1.RangeSelector) ([][2]uint32, error) {
	if selector == nil || len(selector.GetRanges()) == 0 {
		return nil, nil
	}
	type pair struct {
		start uint32
		end   uint32
	}
	items := make([]pair, 0, len(selector.GetRanges()))
	for _, item := range selector.GetRanges() {
		start := item.GetStart()
		end := item.GetEnd()
		if end < start {
			return nil, newError(ErrIRSchema, "range end must be >= start")
		}
		items = append(items, pair{start: start, end: end})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].start == items[j].start {
			return items[i].end < items[j].end
		}
		return items[i].start < items[j].start
	})

	merged := make([][2]uint32, 0, len(items))
	for _, current := range items {
		if len(merged) == 0 {
			merged = append(merged, [2]uint32{current.start, current.end})
			continue
		}
		last := &merged[len(merged)-1]
		if uint64(current.start) <= uint64(last[1])+1 {
			if current.end > last[1] {
				last[1] = current.end
			}
			continue
		}
		merged = append(merged, [2]uint32{current.start, current.end})
	}
	return merged, nil
}

func selectorPayloadBytes(selector *manifestirv1.ManifestSelector) ([]byte, error) {
	if selector == nil {
		return nil, newError(ErrIRSchema, "selector is nil")
	}
	switch selector.GetEncoding() {
	case manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_ROARING:
		payload := selector.GetRoaring()
		if payload == nil {
			return nil, newError(ErrIRSchema, "selector encoding roaring but payload missing")
		}
		return payload.GetBitmap(), nil
	case manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_RANGE:
		payload := selector.GetRange()
		if payload == nil {
			return nil, newError(ErrIRSchema, "selector encoding range but payload missing")
		}
		merged, err := normalizeRanges(payload)
		if err != nil {
			return nil, err
		}
		raw := make([]byte, 0, len(merged)*8)
		buf := make([]byte, 8)
		for _, pair := range merged {
			binary.LittleEndian.PutUint32(buf[0:4], pair[0])
			binary.LittleEndian.PutUint32(buf[4:8], pair[1])
			raw = append(raw, buf...)
		}
		return raw, nil
	case manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_BITSET:
		payload := selector.GetBitset()
		if payload == nil {
			return nil, newError(ErrIRSchema, "selector encoding bitset but payload missing")
		}
		return payload.GetBitsetLe(), nil
	default:
		return nil, newError(ErrIRSchema, "selector encoding is unspecified")
	}
}

func SelectorCardinality(selector *manifestirv1.ManifestSelector) (uint32, error) {
	if selector == nil {
		return 0, newError(ErrIRSchema, "selector is nil")
	}
	switch selector.GetEncoding() {
	case manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_ROARING:
		if selector.GetCardinality() == 0 {
			return 0, newError(ErrIRSchema, "roaring selector requires cardinality")
		}
		return selector.GetCardinality(), nil
	case manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_RANGE:
		merged, err := normalizeRanges(selector.GetRange())
		if err != nil {
			return 0, err
		}
		var total uint64
		for _, pair := range merged {
			total += uint64(pair[1]-pair[0]) + 1
			if total > maxUint32Value {
				return 0, newError(ErrIRSchema, "selector cardinality exceeds uint32")
			}
		}
		return uint32(total), nil
	case manifestirv1.ManifestSelectorEncoding_MANIFEST_SELECTOR_ENCODING_BITSET:
		var total uint64
		for _, item := range selector.GetBitset().GetBitsetLe() {
			total += uint64(bits.OnesCount8(item))
			if total > maxUint32Value {
				return 0, newError(ErrIRSchema, "selector cardinality exceeds uint32")
			}
		}
		return uint32(total), nil
	default:
		return 0, newError(ErrIRSchema, "selector encoding is unspecified")
	}
}

func SelectorChecksum(selector *manifestirv1.ManifestSelector) (string, error) {
	if selector == nil {
		return "", newError(ErrIRSchema, "selector is nil")
	}
	if selector.GetSnapshotId() == "" {
		return "", newError(ErrIRSchema, "selector.snapshot_id is required")
	}
	cardinality, err := SelectorCardinality(selector)
	if err != nil {
		return "", err
	}
	payload, err := selectorPayloadBytes(selector)
	if err != nil {
		return "", err
	}
	digest := sha256.New()
	digest.Write([]byte(selector.GetSnapshotId()))
	digest.Write([]byte{0})

	encodingRaw := make([]byte, 4)
	binary.LittleEndian.PutUint32(encodingRaw, uint32(selector.GetEncoding()))
	digest.Write(encodingRaw)
	digest.Write(payload)

	cardinalityRaw := make([]byte, 4)
	binary.LittleEndian.PutUint32(cardinalityRaw, cardinality)
	digest.Write(cardinalityRaw)
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func ValidateManifestSelector(selector *manifestirv1.ManifestSelector) (uint32, string, error) {
	cardinality, err := SelectorCardinality(selector)
	if err != nil {
		return 0, "", err
	}
	if selector.GetCardinality() > 0 && selector.GetCardinality() != cardinality {
		return 0, "", newError(
			ErrIRSchema,
			"selector cardinality mismatch expected=%d actual=%d",
			selector.GetCardinality(),
			cardinality,
		)
	}
	checksum, err := SelectorChecksum(selector)
	if err != nil {
		return 0, "", err
	}
	if selector.GetChecksum() != "" && selector.GetChecksum() != checksum {
		return 0, "", newError(
			ErrIRSchema,
			"selector checksum mismatch expected=%s actual=%s",
			selector.GetChecksum(),
			checksum,
		)
	}
	return cardinality, checksum, nil
}
