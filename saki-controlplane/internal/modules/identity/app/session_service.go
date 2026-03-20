package app

import (
	"context"
	"errors"
	"net/netip"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

const DefaultRefreshSessionTTL = 30 * 24 * time.Hour

var ErrInvalidRefreshSession = errors.New("invalid refresh session")

type CreateRefreshSessionParams struct {
	PrincipalID uuid.UUID
	TokenHash   string
	UserAgent   string
	IPAddress   *netip.Addr
	LastSeenAt  time.Time
	ExpiresAt   time.Time
}

type RefreshSessionStore interface {
	CreateRefreshSession(ctx context.Context, params CreateRefreshSessionParams) (*identitydomain.RefreshSession, error)
	GetRefreshSessionByTokenHash(ctx context.Context, tokenHash string) (*identitydomain.RefreshSession, error)
	DeleteRefreshSession(ctx context.Context, id uuid.UUID) error
}

type RefreshSessionIssue struct {
	RefreshToken string
	Session      *identitydomain.RefreshSession
}

type SessionService struct {
	store  RefreshSessionStore
	issuer *TokenIssuer
	now    func() time.Time
	ttl    time.Duration
}

func NewSessionService(store RefreshSessionStore, issuer *TokenIssuer) *SessionService {
	if issuer == nil {
		issuer = NewTokenIssuer()
	}
	return &SessionService{
		store:  store,
		issuer: issuer,
		now:    time.Now,
		ttl:    DefaultRefreshSessionTTL,
	}
}

func (s *SessionService) Issue(ctx context.Context, principalID uuid.UUID, userAgent string, ipAddress *netip.Addr) (*RefreshSessionIssue, error) {
	token, tokenHash, err := s.issuer.IssueOpaqueToken()
	if err != nil {
		return nil, err
	}

	now := s.now().UTC()
	session, err := s.store.CreateRefreshSession(ctx, CreateRefreshSessionParams{
		PrincipalID: principalID,
		TokenHash:   tokenHash,
		UserAgent:   userAgent,
		IPAddress:   cloneAddr(ipAddress),
		LastSeenAt:  now,
		ExpiresAt:   now.Add(s.ttl),
	})
	if err != nil {
		return nil, err
	}

	return &RefreshSessionIssue{
		RefreshToken: token,
		Session:      session,
	}, nil
}

func (s *SessionService) Rotate(ctx context.Context, refreshToken string, userAgent string, ipAddress *netip.Addr) (*RefreshSessionIssue, error) {
	tokenHash := s.issuer.HashOpaqueToken(refreshToken)
	current, err := s.store.GetRefreshSessionByTokenHash(ctx, tokenHash)
	if err != nil {
		return nil, err
	}
	if current == nil || current.IsExpired(s.now().UTC()) {
		return nil, ErrInvalidRefreshSession
	}
	if err := s.store.DeleteRefreshSession(ctx, current.ID); err != nil {
		return nil, err
	}

	return s.Issue(ctx, current.PrincipalID, userAgent, ipAddress)
}

func cloneAddr(addr *netip.Addr) *netip.Addr {
	if addr == nil {
		return nil
	}
	copy := *addr
	return &copy
}
