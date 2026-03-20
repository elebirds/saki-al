package domain

import (
	"time"

	"github.com/google/uuid"
)

type PrincipalKind string

const (
	PrincipalKindHumanUser       PrincipalKind = "human_user"
	PrincipalKindAgent           PrincipalKind = "agent"
	PrincipalKindInternalService PrincipalKind = "internal_service"
)

type PrincipalStatus string

const (
	PrincipalStatusActive   PrincipalStatus = "active"
	PrincipalStatusDisabled PrincipalStatus = "disabled"
)

type Principal struct {
	ID          uuid.UUID
	Kind        PrincipalKind
	DisplayName string
	Status      PrincipalStatus
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

func (p Principal) IsDisabled() bool {
	return p.Status == PrincipalStatusDisabled
}
