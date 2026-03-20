package app

import (
	"context"
	"errors"
	"net/netip"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
)

var ErrSelfRegistrationDisabled = errors.New("self registration disabled")

const BuiltinRoleRegisteredUser = "registered_user"

type RegisterCommand struct {
	Email     string
	Password  string
	FullName  string
	UserAgent string
	IPAddress *netip.Addr
}

type RegisterParams struct {
	Email            string
	FullName         string
	PasswordHash     string
	RegisteredAt     time.Time
	RefreshTokenHash string
	RefreshExpiresAt time.Time
	UserAgent        string
	IPAddress        *netip.Addr
}

type RegisterResult struct {
	User identitydomain.User
}

type RegisterStore interface {
	Register(ctx context.Context, params RegisterParams) (*RegisterResult, error)
}

type RegisterUseCase struct {
	store           RegisterStore
	accessTokens    AccessTokenIssuer
	refreshTokens   OpaqueTokenIssuer
	passwords       *PasswordHasher
	accessTokenTTL  time.Duration
	refreshTokenTTL time.Duration
	now             func() time.Time
}

func NewRegisterUseCase(store RegisterStore, accessTokens AccessTokenIssuer, refreshTokens OpaqueTokenIssuer, accessTokenTTL time.Duration) *RegisterUseCase {
	if refreshTokens == nil {
		refreshTokens = NewTokenIssuer()
	}
	return &RegisterUseCase{
		store:           store,
		accessTokens:    accessTokens,
		refreshTokens:   refreshTokens,
		passwords:       NewPasswordHasher(),
		accessTokenTTL:  normalizeAccessTokenTTL(accessTokenTTL),
		refreshTokenTTL: DefaultRefreshSessionTTL,
		now:             time.Now,
	}
}

func (u *RegisterUseCase) Execute(ctx context.Context, cmd RegisterCommand) (*AuthSession, error) {
	passwordHash, err := u.passwords.Hash(cmd.Password)
	if err != nil {
		return nil, err
	}
	refreshToken, refreshTokenHash, err := u.refreshTokens.IssueOpaqueToken()
	if err != nil {
		return nil, err
	}

	now := u.now().UTC()
	result, err := u.store.Register(ctx, RegisterParams{
		Email:            cmd.Email,
		FullName:         cmd.FullName,
		PasswordHash:     passwordHash,
		RegisteredAt:     now,
		RefreshTokenHash: refreshTokenHash,
		RefreshExpiresAt: now.Add(u.refreshTokenTTL),
		UserAgent:        cmd.UserAgent,
		IPAddress:        cloneAddr(cmd.IPAddress),
	})
	if err != nil {
		return nil, err
	}

	accessToken, err := u.accessTokens.IssueTokenContext(ctx, result.User.Email)
	if err != nil {
		return nil, err
	}
	permissions, err := permissionsFromAccessToken(u.accessTokens, accessToken)
	if err != nil {
		return nil, err
	}
	return buildAuthSession(accessToken, refreshToken, u.accessTokenTTL, false, permissions, result.User), nil
}
