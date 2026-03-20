package domain

import (
	"time"

	"github.com/google/uuid"
)

const SystemNameControlplane = "controlplane"

type SystemBinding struct {
	ID          uuid.UUID
	PrincipalID uuid.UUID
	RoleID      uuid.UUID
	SystemName  string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}
