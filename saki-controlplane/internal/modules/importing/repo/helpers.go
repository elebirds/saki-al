package repo

import (
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

func optionalTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	ts := value.Time
	return &ts
}

func pgtypeTimestamptz(value time.Time) pgtype.Timestamptz {
	if value.IsZero() {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: value, Valid: true}
}
