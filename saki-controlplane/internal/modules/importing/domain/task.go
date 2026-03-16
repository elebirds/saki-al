package domain

import (
	"time"

	"github.com/google/uuid"
)

type Task struct {
	ID           uuid.UUID
	UserID       uuid.UUID
	Mode         string
	ResourceType string
	ResourceID   uuid.UUID
	Status       string
	Payload      []byte
	Result       []byte
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

type TaskEvent struct {
	Seq       int64
	TaskID    uuid.UUID
	Event     string
	Phase     string
	Payload   []byte
	CreatedAt time.Time
}
