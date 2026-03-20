package app

import (
	"context"
	"errors"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

type ChangePasswordStore interface {
	FindAccountByPrincipalID(ctx context.Context, principalID uuid.UUID) (*AuthAccount, error)
	ChangePassword(ctx context.Context, params ChangePasswordParams) (*PasswordMutationResult, error)
}

type ChangePasswordUseCase struct {
	store           ChangePasswordStore
	accessTokens    AccessTokenIssuer
	refreshTokens   OpaqueTokenIssuer
	verifier        *CredentialVerifier
	passwords       *PasswordHasher
	accessTokenTTL  time.Duration
	refreshTokenTTL time.Duration
	now             func() time.Time
}

func NewChangePasswordUseCase(store ChangePasswordStore, accessTokens AccessTokenIssuer, refreshTokens OpaqueTokenIssuer, verifier *CredentialVerifier, accessTokenTTL time.Duration) *ChangePasswordUseCase {
	if verifier == nil {
		verifier = NewCredentialVerifier(nil)
	}
	if refreshTokens == nil {
		refreshTokens = NewTokenIssuer()
	}
	return &ChangePasswordUseCase{
		store:           store,
		accessTokens:    accessTokens,
		refreshTokens:   refreshTokens,
		verifier:        verifier,
		passwords:       NewPasswordHasher(),
		accessTokenTTL:  normalizeAccessTokenTTL(accessTokenTTL),
		refreshTokenTTL: DefaultRefreshSessionTTL,
		now:             time.Now,
	}
}

func (u *ChangePasswordUseCase) Execute(ctx context.Context, cmd ChangePasswordCommand) (*AuthSession, error) {
	account, err := u.store.FindAccountByPrincipalID(ctx, cmd.PrincipalID)
	if err != nil {
		return nil, err
	}
	if account == nil || account.IsDisabled() {
		return nil, ErrInvalidCredentials
	}

	credential, err := u.verifyCurrentPassword(account.Credentials, cmd.OldPassword)
	if err != nil {
		return nil, err
	}
	if credential == nil {
		return nil, ErrInvalidCredentials
	}

	passwordHash, err := u.passwords.Hash(cmd.NewPassword)
	if err != nil {
		return nil, err
	}
	refreshToken, refreshTokenHash, err := u.refreshTokens.IssueOpaqueToken()
	if err != nil {
		return nil, err
	}

	now := u.now().UTC()
	result, err := u.store.ChangePassword(ctx, ChangePasswordParams{
		PrincipalID:      cmd.PrincipalID,
		NewPasswordHash:  passwordHash,
		ChangedAt:        now,
		RefreshTokenHash: refreshTokenHash,
		RefreshExpiresAt: now.Add(u.refreshTokenTTL),
		UserAgent:        cmd.UserAgent,
		IPAddress:        cloneAddr(cmd.IPAddress),
	})
	if err != nil {
		return nil, err
	}
	if result == nil {
		return nil, ErrInvalidCredentials
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

func (u *ChangePasswordUseCase) verifyCurrentPassword(credentials []identitydomain.PasswordCredential, rawPassword string) (*identitydomain.PasswordCredential, error) {
	for i := range credentials {
		credential := &credentials[i]
		ok, err := u.verifier.Verify(*credential, rawPassword)
		switch {
		case errors.Is(err, ErrUnsupportedCredentialProvider), errors.Is(err, ErrUnsupportedCredentialScheme):
			continue
		case err != nil:
			return nil, err
		case ok:
			return credential, nil
		}
	}
	return nil, nil
}
