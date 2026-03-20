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
var ErrRefreshSessionNotConsumed = errors.New("refresh session not consumed")

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
	RotateRefreshSession(ctx context.Context, params RotateRefreshSessionParams) (*identitydomain.RefreshSession, error)
}

type RotateRefreshSessionParams struct {
	CurrentTokenHash string
	Now              time.Time
	NewTokenHash     string
	UserAgent        string
	IPAddress        *netip.Addr
	ExpiresAt        time.Time
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
	// 关键设计：refresh session 必须落库，而不是做成完全自包含的长效 token。
	// 只有服务端持久化会话，才能支持显式注销、轮换旧 token、凭据变更后立即失效，以及迁移期对旧会话策略的可控兼容。
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
	currentTokenHash := s.issuer.HashOpaqueToken(refreshToken)
	newToken, newTokenHash, err := s.issuer.IssueOpaqueToken()
	if err != nil {
		return nil, err
	}

	now := s.now().UTC()
	rotated, err := s.store.RotateRefreshSession(ctx, RotateRefreshSessionParams{
		CurrentTokenHash: currentTokenHash,
		Now:              now,
		NewTokenHash:     newTokenHash,
		UserAgent:        userAgent,
		IPAddress:        cloneAddr(ipAddress),
		ExpiresAt:        now.Add(s.ttl),
	})
	if err != nil {
		if errors.Is(err, ErrRefreshSessionNotConsumed) {
			return nil, ErrInvalidRefreshSession
		}
		return nil, err
	}

	return &RefreshSessionIssue{
		RefreshToken: newToken,
		Session:      rotated,
	}, nil
}

func cloneAddr(addr *netip.Addr) *netip.Addr {
	if addr == nil {
		return nil
	}
	copy := *addr
	return &copy
}
