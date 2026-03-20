package domain

import (
	"net/netip"
	"time"

	"github.com/google/uuid"
)

type RefreshSession struct {
	ID          uuid.UUID
	PrincipalID uuid.UUID
	TokenHash   string
	UserAgent   string
	IPAddress   *netip.Addr
	LastSeenAt  time.Time
	ExpiresAt   time.Time
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

func (s RefreshSession) IsExpired(now time.Time) bool {
	return !s.ExpiresAt.IsZero() && !s.ExpiresAt.After(now)
}
