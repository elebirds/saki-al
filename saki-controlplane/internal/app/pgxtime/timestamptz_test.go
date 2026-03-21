package pgxtime

import (
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

func TestOptionalTimestamptzReturnsNilForInvalidValue(t *testing.T) {
	if got := OptionalTimestamptz(pgtype.Timestamptz{}); got != nil {
		t.Fatalf("OptionalTimestamptz(invalid) = %v, want nil", got)
	}
}

func TestOptionalTimestamptzReturnsCopiedTime(t *testing.T) {
	want := time.Date(2026, 3, 21, 12, 34, 56, 0, time.UTC)
	got := OptionalTimestamptz(pgtype.Timestamptz{Time: want, Valid: true})
	if got == nil || !got.Equal(want) {
		t.Fatalf("OptionalTimestamptz(valid) = %v, want %v", got, want)
	}
}

func TestTimestamptzReturnsInvalidForZeroTime(t *testing.T) {
	got := Timestamptz(time.Time{})
	if got.Valid {
		t.Fatalf("Timestamptz(zero) = %+v, want invalid", got)
	}
}

func TestTimestamptzReturnsValidForNonZeroTime(t *testing.T) {
	want := time.Date(2026, 3, 21, 12, 34, 56, 0, time.UTC)
	got := Timestamptz(want)
	if !got.Valid || !got.Time.Equal(want) {
		t.Fatalf("Timestamptz(valid) = %+v, want valid time %v", got, want)
	}
}
