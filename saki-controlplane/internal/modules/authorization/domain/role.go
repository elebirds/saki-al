package domain

import (
	"time"

	"github.com/google/uuid"
)

type RoleScopeKind string

const (
	RoleScopeSystem   RoleScopeKind = "system"
	RoleScopeResource RoleScopeKind = "resource"
)

type Role struct {
	ID          uuid.UUID
	ScopeKind   RoleScopeKind
	Name        string
	DisplayName string
	Description string
	BuiltIn     bool
	Mutable     bool
	Color       string
	IsSupremo   bool
	SortOrder   int
	CreatedAt   time.Time
	UpdatedAt   time.Time
}
