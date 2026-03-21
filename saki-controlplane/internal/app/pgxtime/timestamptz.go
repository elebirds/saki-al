package pgxtime

import (
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

// OptionalTimestamptz 把可空 timestamptz 转成 Go 指针，统一 repo 层的空值语义。
func OptionalTimestamptz(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	ts := value.Time
	return &ts
}

// Timestamptz 把零值时间映射成 SQL NULL，避免各 repo 重复判断 zero time。
func Timestamptz(value time.Time) pgtype.Timestamptz {
	if value.IsZero() {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: value, Valid: true}
}
