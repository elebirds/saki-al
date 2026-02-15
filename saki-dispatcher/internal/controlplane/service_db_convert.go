package controlplane

import (
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

func toPGUUID(raw string) (pgtype.UUID, error) {
	var id pgtype.UUID
	if err := id.Scan(strings.TrimSpace(raw)); err != nil {
		return pgtype.UUID{}, err
	}
	return id, nil
}

func toPGUUIDOrZero(raw string) pgtype.UUID {
	id, err := toPGUUID(raw)
	if err != nil {
		return pgtype.UUID{}
	}
	return id
}

func toPGUUIDs(raw []string) ([]pgtype.UUID, error) {
	items := make([]pgtype.UUID, 0, len(raw))
	for _, item := range raw {
		id, err := toPGUUID(item)
		if err != nil {
			return nil, err
		}
		items = append(items, id)
	}
	return items, nil
}

func toPGText(raw string) pgtype.Text {
	return pgtype.Text{
		String: strings.TrimSpace(raw),
		Valid:  true,
	}
}

func toNullablePGText(raw string) pgtype.Text {
	value := strings.TrimSpace(raw)
	if value == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: value, Valid: true}
}

func toNullablePGUUID(raw string) (pgtype.UUID, error) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return pgtype.UUID{}, nil
	}
	return toPGUUID(value)
}

func toPGTimestamp(ts time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{
		Time:  ts,
		Valid: true,
	}
}

func toPGInt4(value *int) pgtype.Int4 {
	if value == nil {
		return pgtype.Int4{}
	}
	return pgtype.Int4{Int32: int32(*value), Valid: true}
}

func asString(raw any) string {
	switch value := raw.(type) {
	case nil:
		return ""
	case string:
		return strings.TrimSpace(value)
	case []byte:
		return strings.TrimSpace(string(value))
	default:
		return strings.TrimSpace(fmt.Sprintf("%v", value))
	}
}

func timestampPtr(ts pgtype.Timestamp) *time.Time {
	if !ts.Valid {
		return nil
	}
	value := ts.Time.UTC()
	return &value
}
