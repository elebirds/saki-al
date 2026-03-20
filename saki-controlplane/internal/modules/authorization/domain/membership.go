package domain

import (
	"time"

	"github.com/google/uuid"
)

const (
	ResourceTypeProject = "project"
	ResourceTypeDataset = "dataset"
)

type ResourceRef struct {
	Type string
	ID   uuid.UUID
}

type ResourceMembership struct {
	ID           uuid.UUID
	PrincipalID  uuid.UUID
	RoleID       uuid.UUID
	ResourceType string
	ResourceID   uuid.UUID
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

func (m ResourceMembership) Matches(ref ResourceRef) bool {
	return m.ResourceType == ref.Type && m.ResourceID == ref.ID
}
