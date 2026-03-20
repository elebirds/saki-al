package app

import (
	"context"
	"net/netip"
	"time"

	"github.com/google/uuid"
)

type RefreshAccountStore interface {
	FindAccountByPrincipalID(ctx context.Context, principalID uuid.UUID) (*AuthAccount, error)
}

type RefreshSessionRotator interface {
	Rotate(ctx context.Context, refreshToken string, userAgent string, ipAddress *netip.Addr) (*RefreshSessionIssue, error)
}

type RefreshUseCase struct {
	store           RefreshAccountStore
	accessTokens    AccessTokenIssuer
	refreshSessions RefreshSessionRotator
	accessTokenTTL  time.Duration
}

func NewRefreshUseCase(store RefreshAccountStore, accessTokens AccessTokenIssuer, refreshSessions RefreshSessionRotator, accessTokenTTL time.Duration) *RefreshUseCase {
	return &RefreshUseCase{
		store:           store,
		accessTokens:    accessTokens,
		refreshSessions: refreshSessions,
		accessTokenTTL:  normalizeAccessTokenTTL(accessTokenTTL),
	}
}

func (u *RefreshUseCase) Execute(ctx context.Context, cmd RefreshCommand) (*AuthSession, error) {
	rotated, err := u.refreshSessions.Rotate(ctx, cmd.RefreshToken, cmd.UserAgent, cloneAddr(cmd.IPAddress))
	if err != nil {
		return nil, err
	}

	account, err := u.store.FindAccountByPrincipalID(ctx, rotated.Session.PrincipalID)
	if err != nil {
		return nil, err
	}
	if account == nil || account.IsDisabled() {
		return nil, ErrInvalidCredentials
	}

	accessToken, err := u.accessTokens.IssueTokenContext(ctx, account.User.Email)
	if err != nil {
		return nil, err
	}
	permissions, err := permissionsFromAccessToken(u.accessTokens, accessToken)
	if err != nil {
		return nil, err
	}

	mustChangePassword := false
	if credential := account.ActivePasswordCredential(); credential != nil {
		mustChangePassword = credential.MustChangePassword
	}
	return buildAuthSession(accessToken, rotated.RefreshToken, u.accessTokenTTL, mustChangePassword, permissions, account.User), nil
}
