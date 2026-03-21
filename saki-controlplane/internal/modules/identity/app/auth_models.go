package app

import (
	"context"
	"net/netip"
	"time"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

type AccessTokenIssuer interface {
	IssueTokenContext(ctx context.Context, identifier string) (string, error)
	ParseToken(token string) (*accessapp.Claims, error)
}

type OpaqueTokenIssuer interface {
	IssueOpaqueToken() (token string, tokenHash string, err error)
}

type SessionUser struct {
	PrincipalID uuid.UUID
	Email       string
	FullName    string
}

type AuthSession struct {
	AccessToken        string
	RefreshToken       string
	ExpiresIn          int64
	MustChangePassword bool
	Permissions        []string
	User               SessionUser
}

type AuthAccount struct {
	Principal   identitydomain.Principal
	User        identitydomain.User
	Credentials []identitydomain.PasswordCredential
}

func (a *AuthAccount) IsDisabled() bool {
	return a == nil ||
		a.Principal.IsDisabled() ||
		a.User.State == identitydomain.UserStateDisabled ||
		a.User.State == identitydomain.UserStateDeleted
}

func (a *AuthAccount) DisplayFullName() string {
	if a == nil || a.User.FullName == nil {
		return ""
	}
	return *a.User.FullName
}

func (a *AuthAccount) ActivePasswordCredential() *identitydomain.PasswordCredential {
	if a == nil {
		return nil
	}

	for i := range a.Credentials {
		credential := &a.Credentials[i]
		if credential.Provider != identitydomain.CredentialProviderLocalPassword {
			continue
		}
		if credential.Scheme == identitydomain.PasswordSchemeArgon2id {
			return credential
		}
	}
	return nil
}

type LoginCommand struct {
	Identifier string
	Password   string
	UserAgent  string
	IPAddress  *netip.Addr
}

type RefreshCommand struct {
	RefreshToken string
	UserAgent    string
	IPAddress    *netip.Addr
}

type ChangePasswordCommand struct {
	PrincipalID uuid.UUID
	OldPassword string
	NewPassword string
	UserAgent   string
	IPAddress   *netip.Addr
}

type ChangePasswordParams struct {
	PrincipalID      uuid.UUID
	NewPasswordHash  string
	ChangedAt        time.Time
	RefreshTokenHash string
	RefreshExpiresAt time.Time
	UserAgent        string
	IPAddress        *netip.Addr
}

type PasswordMutationResult struct {
	User identitydomain.User
}

func buildAuthSession(accessToken string, refreshToken string, accessTokenTTL time.Duration, mustChangePassword bool, permissions []string, user identitydomain.User) *AuthSession {
	return &AuthSession{
		AccessToken:        accessToken,
		RefreshToken:       refreshToken,
		ExpiresIn:          int64(accessTokenTTL.Seconds()),
		MustChangePassword: mustChangePassword,
		Permissions:        append([]string(nil), permissions...),
		User: SessionUser{
			PrincipalID: user.PrincipalID,
			Email:       user.Email,
			FullName:    displayFullName(user),
		},
	}
}

func displayFullName(user identitydomain.User) string {
	if user.FullName == nil {
		return ""
	}
	return *user.FullName
}

func normalizeAccessTokenTTL(ttl time.Duration) time.Duration {
	if ttl <= 0 {
		return 10 * time.Minute
	}
	return ttl
}

func permissionsFromAccessToken(accessTokens AccessTokenIssuer, token string) ([]string, error) {
	claims, err := accessTokens.ParseToken(token)
	if err != nil {
		return nil, err
	}
	if claims == nil {
		return []string{}, nil
	}
	// 关键设计：identity 登录/刷新等响应里的 permissions 不再单独查库，
	// 而是直接复用刚签发 access token 中已经冻结好的权限快照，避免重复查询与双份语义来源。
	return append([]string{}, claims.Permissions...), nil
}
