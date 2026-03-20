package app

import (
	"context"
	"errors"
	"net/netip"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

var ErrInvalidCredentials = errors.New("invalid credentials")

type LoginAccountStore interface {
	FindAccountByIdentifier(ctx context.Context, identifier string) (*AuthAccount, error)
	UpgradePasswordCredential(ctx context.Context, params UpgradePasswordCredentialParams) error
}

type RefreshSessionIssuer interface {
	Issue(ctx context.Context, principalID uuid.UUID, userAgent string, ipAddress *netip.Addr) (*RefreshSessionIssue, error)
}

type LoginUseCase struct {
	store           LoginAccountStore
	accessTokens    AccessTokenIssuer
	refreshSessions RefreshSessionIssuer
	verifier        *CredentialVerifier
	passwords       *PasswordHasher
	accessTokenTTL  time.Duration
	now             func() time.Time
}

func NewLoginUseCase(store LoginAccountStore, accessTokens AccessTokenIssuer, refreshSessions RefreshSessionIssuer, verifier *CredentialVerifier, accessTokenTTL time.Duration) *LoginUseCase {
	if verifier == nil {
		verifier = NewCredentialVerifier(nil)
	}
	return &LoginUseCase{
		store:           store,
		accessTokens:    accessTokens,
		refreshSessions: refreshSessions,
		verifier:        verifier,
		passwords:       NewPasswordHasher(),
		accessTokenTTL:  normalizeAccessTokenTTL(accessTokenTTL),
		now:             time.Now,
	}
}

func (u *LoginUseCase) Execute(ctx context.Context, cmd LoginCommand) (*AuthSession, error) {
	account, err := u.store.FindAccountByIdentifier(ctx, cmd.Identifier)
	if err != nil {
		return nil, err
	}
	if account == nil || account.IsDisabled() {
		return nil, ErrInvalidCredentials
	}

	credential, err := u.verifyPassword(account.Credentials, cmd.Password)
	if err != nil {
		return nil, err
	}
	if credential == nil {
		return nil, ErrInvalidCredentials
	}

	if credential.Scheme == identitydomain.PasswordSchemeLegacyFrontendSHA256Argon2 {
		passwordHash, err := u.passwords.Hash(cmd.Password)
		if err != nil {
			return nil, err
		}
		if err := u.store.UpgradePasswordCredential(ctx, UpgradePasswordCredentialParams{
			PrincipalID:        account.Principal.ID,
			OldScheme:          credential.Scheme,
			NewScheme:          identitydomain.PasswordSchemeArgon2id,
			NewPasswordHash:    passwordHash,
			MustChangePassword: credential.MustChangePassword,
			PasswordChangedAt:  u.now().UTC(),
		}); err != nil {
			return nil, err
		}
		credential.Scheme = identitydomain.PasswordSchemeArgon2id
		credential.PasswordHash = passwordHash
	}

	refresh, err := u.refreshSessions.Issue(ctx, account.Principal.ID, cmd.UserAgent, cloneAddr(cmd.IPAddress))
	if err != nil {
		return nil, err
	}

	accessToken, err := u.accessTokens.IssueTokenContext(ctx, account.User.Email)
	if err != nil {
		return nil, err
	}
	permissions, err := permissionsFromAccessToken(u.accessTokens, accessToken)
	if err != nil {
		return nil, err
	}

	return buildAuthSession(accessToken, refresh.RefreshToken, u.accessTokenTTL, credential.MustChangePassword, permissions, account.User), nil
}

func (u *LoginUseCase) verifyPassword(credentials []identitydomain.PasswordCredential, rawPassword string) (*identitydomain.PasswordCredential, error) {
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
