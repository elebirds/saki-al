package sakir

import "fmt"

const (
	// ErrIRSchema 表示 schema 级别错误（字段缺失、枚举不支持、值域非法等）。
	ErrIRSchema = "ERR_IR_SCHEMA"
	// ErrIRGeometry 表示几何语义错误（NaN/Inf、宽高非法、shape 缺失等）。
	ErrIRGeometry = "ERR_IR_GEOMETRY"
	// ErrIRCodecUnsupported 表示 payload codec 未实现或不支持。
	ErrIRCodecUnsupported = "ERR_IR_CODEC_UNSUPPORTED"
	// ErrIRCompressionUnsupported 表示压缩算法不支持或解压失败。
	ErrIRCompressionUnsupported = "ERR_IR_COMPRESSION_UNSUPPORTED"
	// ErrIRChecksumMismatch 表示 checksum 校验失败。
	ErrIRChecksumMismatch = "ERR_IR_CHECKSUM_MISMATCH"
)

// Error 是 saki-ir Go SDK 的统一错误类型。
type Error struct {
	// Code 是稳定错误码（ERR_IR_*）。
	Code string
	// Message 是面向开发者的错误描述。
	Message string
}

// Error 实现 error 接口。
func (e *Error) Error() string {
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func newError(code string, format string, args ...any) error {
	return &Error{Code: code, Message: fmt.Sprintf(format, args...)}
}
