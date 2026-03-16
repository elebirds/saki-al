package domain

import (
	"time"

	"github.com/google/uuid"
)

type PreviewManifest struct {
	Token           string
	Mode            string
	ProjectID       uuid.UUID
	UploadSessionID uuid.UUID
	Manifest        []byte
	ParamsHash      string
	ExpiresAt       time.Time
	CreatedAt       time.Time
}
