package domain

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

type Setting struct {
	ID             uuid.UUID
	InstallationID uuid.UUID
	Key            string
	Value          json.RawMessage
	CreatedAt      time.Time
	UpdatedAt      time.Time
}
