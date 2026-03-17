package domain

import "github.com/google/uuid"

const SubjectTypeUser = "user"

type PrincipalStatus string

const (
	PrincipalStatusActive   PrincipalStatus = "active"
	PrincipalStatusDisabled PrincipalStatus = "disabled"
)

type Principal struct {
	ID          uuid.UUID
	SubjectType string
	SubjectKey  string
	DisplayName string
	Status      PrincipalStatus
}

func (p Principal) IsDisabled() bool {
	return p.Status == PrincipalStatusDisabled
}
