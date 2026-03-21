package app

import (
	"context"
	"errors"
	"net/netip"
	"time"

	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	"github.com/google/uuid"
)

var ErrAlreadyInitialized = errors.New("system already initialized")

const DefaultRefreshSessionTTL = identityapp.DefaultRefreshSessionTTL

const BuiltinRoleSuperAdmin = "super_admin"

type AccessTokenIssuer interface {
	IssueTokenContext(ctx context.Context, userID string) (string, error)
}

type OpaqueTokenIssuer interface {
	IssueOpaqueToken() (token string, tokenHash string, err error)
}

type InitializeSystemCommand struct {
	Email     string
	Password  string
	FullName  string
	UserAgent string
	IPAddress *netip.Addr
}

type InitializeSystemParams struct {
	Email            string
	FullName         string
	PasswordHash     string
	RefreshTokenHash string
	UserAgent        string
	IPAddress        *netip.Addr
	InitializedAt    time.Time
	RefreshExpiresAt time.Time
}

type InitializeSystemResult struct {
	PrincipalID uuid.UUID
	Email       string
	FullName    string
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
	User               SessionUser
}

type InitializeSystemStore interface {
	InitializeSystem(ctx context.Context, params InitializeSystemParams) (*InitializeSystemResult, error)
}

type InitializeSystemUseCase struct {
	store             InitializeSystemStore
	accessTokens      AccessTokenIssuer
	refreshTokens     OpaqueTokenIssuer
	passwords         *identityapp.PasswordHasher
	now               func() time.Time
	accessTokenTTL    time.Duration
	refreshSessionTTL time.Duration
}

func NewInitializeSystemUseCase(store InitializeSystemStore, accessTokens AccessTokenIssuer, refreshTokens OpaqueTokenIssuer, accessTokenTTL time.Duration) *InitializeSystemUseCase {
	if refreshTokens == nil {
		refreshTokens = identityapp.NewTokenIssuer()
	}
	if accessTokenTTL <= 0 {
		accessTokenTTL = 10 * time.Minute
	}
	return &InitializeSystemUseCase{
		store:             store,
		accessTokens:      accessTokens,
		refreshTokens:     refreshTokens,
		passwords:         identityapp.NewPasswordHasher(),
		now:               time.Now,
		accessTokenTTL:    accessTokenTTL,
		refreshSessionTTL: DefaultRefreshSessionTTL,
	}
}

// 关键设计：初始化事务只负责把“系统已安装”这件事一次性写实：
// 角色、首个主体、密码凭据、默认设置与首个 refresh session 一起提交。
// access token 是可重建的短效签名结果，因此放在事务提交后签发，避免把纯派生值混入事务写路径。
func (u *InitializeSystemUseCase) Execute(ctx context.Context, cmd InitializeSystemCommand) (*AuthSession, error) {
	passwordHash, err := u.passwords.Hash(cmd.Password)
	if err != nil {
		return nil, err
	}
	refreshToken, refreshTokenHash, err := u.refreshTokens.IssueOpaqueToken()
	if err != nil {
		return nil, err
	}

	now := u.now().UTC()
	result, err := u.store.InitializeSystem(ctx, InitializeSystemParams{
		Email:            cmd.Email,
		FullName:         cmd.FullName,
		PasswordHash:     passwordHash,
		RefreshTokenHash: refreshTokenHash,
		UserAgent:        cmd.UserAgent,
		IPAddress:        cloneAddr(cmd.IPAddress),
		InitializedAt:    now,
		RefreshExpiresAt: now.Add(u.refreshSessionTTL),
	})
	if err != nil {
		return nil, err
	}

	// 这里必须使用事务提交后拿到的持久化结果，而不是直接回用请求参数。
	// 这样即便后续在落库路径里引入 email 规范化，也不会出现“系统已初始化但首个 access token 因查找键不一致而签发失败”。
	accessToken, err := u.accessTokens.IssueTokenContext(ctx, result.Email)
	if err != nil {
		return nil, err
	}

	return &AuthSession{
		AccessToken:        accessToken,
		RefreshToken:       refreshToken,
		ExpiresIn:          int64(u.accessTokenTTL.Seconds()),
		MustChangePassword: false,
		User: SessionUser{
			PrincipalID: result.PrincipalID,
			Email:       result.Email,
			FullName:    result.FullName,
		},
	}, nil
}

func cloneAddr(addr *netip.Addr) *netip.Addr {
	if addr == nil {
		return nil
	}
	copy := *addr
	return &copy
}
