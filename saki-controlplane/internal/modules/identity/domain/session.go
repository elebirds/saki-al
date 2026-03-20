package domain

import (
	"net/netip"
	"time"

	"github.com/google/uuid"
)

type RefreshSession struct {
	ID               uuid.UUID
	PrincipalID      uuid.UUID
	FamilyID         uuid.UUID
	TokenHash        string
	UserAgent        string
	IPAddress        *netip.Addr
	LastSeenAt       time.Time
	ExpiresAt        time.Time
	CreatedAt        time.Time
	UpdatedAt        time.Time
	RotatedFrom      *uuid.UUID
	ReplacedBy       *uuid.UUID
	RevokedAt        *time.Time
	ReplayDetectedAt *time.Time
}

func (s RefreshSession) IsExpired(now time.Time) bool {
	return !s.ExpiresAt.IsZero() && !s.ExpiresAt.After(now)
}

func (s RefreshSession) IsRevoked() bool {
	return s.RevokedAt != nil
}
