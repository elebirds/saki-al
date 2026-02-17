package sakir

import (
	"fmt"
	"hash/crc32"
	"sync"

	"github.com/klauspost/compress/zstd"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/proto"
)

var (
	crc32cTable  = crc32.MakeTable(crc32.Castagnoli)
	encoderPools sync.Map // map[int]*sync.Pool
	decoderPool  = sync.Pool{
		New: func() any {
			decoder, err := zstd.NewReader(nil)
			if err != nil {
				panic(err)
			}
			return decoder
		},
	}
)

// checksumCRC32C 计算 CRC32C(Castagnoli)。
func checksumCRC32C(data []byte) uint32 {
	return crc32.Checksum(data, crc32cTable)
}

// Encode 将 DataBatchIR 编码为 EncodedPayload。
//
// 行为语义：
// - 不会原地修改输入 batch
// - 会先调用 Validate(batch)
// - checksum 覆盖范围是“未压缩 payloadRaw”
// - 压缩策略由 threshold/level 控制（v1 默认建议 threshold=32768, level=3）
//
// Spec: docs/IR_SPEC.md#9-encoded-payload
func Encode(batch *annotationirv1.DataBatchIR, threshold int, level int) (*annotationirv1.EncodedPayload, error) {
	if batch == nil {
		return nil, newError(ErrIRSchema, "batch is nil")
	}
	if threshold < 0 {
		threshold = 0
	}
	if level == 0 {
		level = 3
	}
	if level < 1 || level > 22 {
		return nil, newError(ErrIRSchema, "zstd level must be in [1,22]")
	}

	if err := Validate(batch); err != nil {
		return nil, err
	}

	payloadRaw, err := proto.Marshal(batch)
	if err != nil {
		return nil, fmt.Errorf("marshal DataBatchIR: %w", err)
	}

	compression := annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_NONE
	payload := payloadRaw
	if len(payloadRaw) >= threshold {
		payload, err = compressZSTD(payloadRaw, level)
		if err != nil {
			return nil, err
		}
		compression = annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_ZSTD
	}

	stats := collectStats(batch)
	stats.PayloadSize = uint64(len(payload))
	stats.UncompressedSize = uint64(len(payloadRaw))

	header := &annotationirv1.PayloadHeader{
		Schema:        annotationirv1.PayloadSchema_PAYLOAD_SCHEMA_DATA_BATCH_IR,
		SchemaVersion: 1,
		Codec:         annotationirv1.PayloadCodec_PAYLOAD_CODEC_PROTOBUF,
		Compression:   compression,
		ChecksumAlgo:  annotationirv1.PayloadChecksumAlgo_PAYLOAD_CHECKSUM_ALGO_CRC32C,
		Checksum:      checksumCRC32C(payloadRaw),
		Stats:         stats,
	}

	return &annotationirv1.EncodedPayload{Header: header, Payload: payload}, nil
}

// Decode 将 EncodedPayload 解码为 DataBatchIR。
//
// 行为语义：
// - 先按 compression 得到未压缩 payloadRaw
// - 校验 checksum（覆盖 payloadRaw）
// - 按 codec 反序列化（v1 仅支持 PROTOBUF）
// - 成功反序列化后默认执行 Normalize（in-place on decoded object）
//
// Spec: docs/IR_SPEC.md#9-encoded-payload
func Decode(encoded *annotationirv1.EncodedPayload) (*annotationirv1.DataBatchIR, error) {
	if encoded == nil {
		return nil, newError(ErrIRSchema, "encoded payload is nil")
	}
	header := ReadHeader(encoded)
	if header == nil {
		return nil, newError(ErrIRSchema, "header is missing")
	}

	if header.GetSchema() != annotationirv1.PayloadSchema_PAYLOAD_SCHEMA_DATA_BATCH_IR {
		return nil, newError(ErrIRSchema, "unsupported schema: %v", header.GetSchema())
	}
	if header.GetSchemaVersion() != 1 {
		return nil, newError(ErrIRSchema, "unsupported schema_version: %d", header.GetSchemaVersion())
	}

	payloadRaw, err := decodeCompression(header.GetCompression(), encoded.GetPayload())
	if err != nil {
		return nil, err
	}

	if header.GetChecksumAlgo() != annotationirv1.PayloadChecksumAlgo_PAYLOAD_CHECKSUM_ALGO_CRC32C {
		return nil, newError(ErrIRSchema, "unsupported checksum algo: %v", header.GetChecksumAlgo())
	}
	actual := checksumCRC32C(payloadRaw)
	if actual != header.GetChecksum() {
		return nil, newError(
			ErrIRChecksumMismatch,
			"checksum mismatch: expected=%d actual=%d",
			header.GetChecksum(),
			actual,
		)
	}

	batch := &annotationirv1.DataBatchIR{}
	switch header.GetCodec() {
	case annotationirv1.PayloadCodec_PAYLOAD_CODEC_PROTOBUF:
		if err := proto.Unmarshal(payloadRaw, batch); err != nil {
			return nil, fmt.Errorf("unmarshal DataBatchIR: %w", err)
		}
	case annotationirv1.PayloadCodec_PAYLOAD_CODEC_MSGPACK:
		return nil, newError(ErrIRCodecUnsupported, "MSGPACK codec is not implemented")
	default:
		return nil, newError(ErrIRCodecUnsupported, "unsupported codec: %v", header.GetCodec())
	}

	if err := Normalize(batch); err != nil {
		return nil, err
	}
	return batch, nil
}

// ReadHeader 返回 EncodedPayload 中 header 的引用（非拷贝）。
//
// 该函数用于 header-only 调度读取；调用方应视为只读。
//
// Spec: docs/IR_SPEC.md#10-header-only-behavior
func ReadHeader(encoded *annotationirv1.EncodedPayload) *annotationirv1.PayloadHeader {
	if encoded == nil || encoded.GetHeader() == nil {
		return nil
	}
	// 语义固定为返回引用（非拷贝）。
	return encoded.GetHeader()
}

func decodeCompression(compression annotationirv1.PayloadCompression, payload []byte) ([]byte, error) {
	// Spec: docs/IR_SPEC.md#9-encoded-payload
	switch compression {
	case annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_NONE:
		return payload, nil
	case annotationirv1.PayloadCompression_PAYLOAD_COMPRESSION_ZSTD:
		return decompressZSTD(payload)
	default:
		return nil, newError(ErrIRCompressionUnsupported, "unsupported compression: %v", compression)
	}
}

func collectStats(batch *annotationirv1.DataBatchIR) *annotationirv1.PayloadStats {
	// Spec: docs/IR_SPEC.md#9-encoded-payload
	stats := &annotationirv1.PayloadStats{ItemCount: uint32(len(batch.GetItems()))}
	for _, item := range batch.GetItems() {
		switch {
		case item.GetAnnotation() != nil:
			stats.AnnotationCount++
		case item.GetSample() != nil:
			stats.SampleCount++
		case item.GetLabel() != nil:
			stats.LabelCount++
		}
	}
	return stats
}

func compressZSTD(raw []byte, level int) ([]byte, error) {
	pool := getEncoderPool(level)
	encoder := pool.Get().(*zstd.Encoder)
	defer pool.Put(encoder)

	return encoder.EncodeAll(raw, make([]byte, 0, len(raw))), nil
}

func decompressZSTD(payload []byte) ([]byte, error) {
	decoder := decoderPool.Get().(*zstd.Decoder)
	defer decoderPool.Put(decoder)

	out, err := decoder.DecodeAll(payload, nil)
	if err != nil {
		return nil, newError(ErrIRCompressionUnsupported, "zstd decompress failed: %v", err)
	}
	return out, nil
}

func getEncoderPool(level int) *sync.Pool {
	if pool, ok := encoderPools.Load(level); ok {
		return pool.(*sync.Pool)
	}

	created := &sync.Pool{
		New: func() any {
			encoder, err := zstd.NewWriter(nil, zstd.WithEncoderLevel(zstd.EncoderLevelFromZstd(level)))
			if err != nil {
				panic(err)
			}
			return encoder
		},
	}
	actual, _ := encoderPools.LoadOrStore(level, created)
	return actual.(*sync.Pool)
}
