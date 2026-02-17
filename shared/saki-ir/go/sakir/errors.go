package sakir

import "fmt"

const (
	ErrIRSchema                 = "ERR_IR_SCHEMA"
	ErrIRGeometry               = "ERR_IR_GEOMETRY"
	ErrIRCodecUnsupported       = "ERR_IR_CODEC_UNSUPPORTED"
	ErrIRCompressionUnsupported = "ERR_IR_COMPRESSION_UNSUPPORTED"
	ErrIRChecksumMismatch       = "ERR_IR_CHECKSUM_MISMATCH"
)

type Error struct {
	Code    string
	Message string
}

func (e *Error) Error() string {
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func newError(code string, format string, args ...any) error {
	return &Error{Code: code, Message: fmt.Sprintf(format, args...)}
}
