package domain

import (
	"time"

	"github.com/google/uuid"
)

type UploadSession struct {
	ID          uuid.UUID
	UserID      uuid.UUID
	Mode        string
	FileName    string
	ObjectKey   string
	ContentType string
	Status      string
	CompletedAt *time.Time
	AbortedAt   *time.Time
	CreatedAt   time.Time
	UpdatedAt   time.Time
}
