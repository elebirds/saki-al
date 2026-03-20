package app

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
)

var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrForbidden    = errors.New("forbidden")
)

type Claims struct {
	PrincipalID uuid.UUID
	UserID      string
	Permissions []string
	ExpiresAt   time.Time
}

func (c *Claims) HasPermission(permission string) bool {
	for _, candidate := range c.Permissions {
		if candidate == permission {
			return true
		}
	}
	return false
}

type Authenticator struct {
	secret []byte
	ttl    time.Duration
	now    func() time.Time
	store  ClaimsStore
}

func NewAuthenticator(secret string, ttl time.Duration) *Authenticator {
	return &Authenticator{
		secret: []byte(secret),
		ttl:    ttl,
		now:    time.Now,
	}
}

func (a *Authenticator) WithStore(store ClaimsStore) *Authenticator {
	a.store = store
	return a
}

func (a *Authenticator) IssueToken(userID string, _ []string) (string, error) {
	return a.IssueTokenContext(context.Background(), userID)
}

func (a *Authenticator) IssueTokenContext(ctx context.Context, userID string) (string, error) {
	if a.store == nil {
		return "", ErrMissingAccessStore
	}

	// access 这里只保留迁移期 HTTP auth 外壳职责，claims 快照统一从 identity/authorization 聚合装载。
	snapshot, err := a.store.LoadClaimsByUserID(ctx, userID)
	if err != nil {
		return "", err
	}
	return a.issueTokenFromSnapshot(snapshot)
}

func (a *Authenticator) IssueBootstrapTokenContext(ctx context.Context, userID string) (string, error) {
	if a.store == nil {
		return "", ErrMissingAccessStore
	}

	bootstrapStore, ok := a.store.(BootstrapClaimsStore)
	if !ok {
		return "", ErrUnauthorized
	}

	// 关键设计：legacy /auth/login 只允许迁移期 bootstrap principal 继续使用。
	// 新的人类控制面 identity 用户必须走后续真正带密码校验的 /auth/login，而不能借旧壳接口无密码拿 token。
	snapshot, err := bootstrapStore.LoadBootstrapClaimsByUserID(ctx, userID)
	if err != nil {
		return "", err
	}
	return a.issueTokenFromSnapshot(snapshot)
}

func (a *Authenticator) AuthenticateContext(ctx context.Context, token string) (*Claims, error) {
	if a.store == nil {
		return nil, ErrMissingAccessStore
	}

	claims, err := a.ParseToken(token)
	if err != nil {
		return nil, err
	}

	snapshot, err := a.store.LoadClaimsByPrincipalID(ctx, claims.PrincipalID)
	if err != nil {
		return nil, err
	}
	if snapshot == nil {
		return nil, ErrUnauthorized
	}
	if snapshot.PrincipalID != claims.PrincipalID || snapshot.UserID != claims.UserID {
		return nil, ErrUnauthorized
	}

	return claimsFromSnapshot(snapshot, claims.ExpiresAt), nil
}

func (a *Authenticator) ParseToken(token string) (*Claims, error) {
	payload, signature, ok := splitToken(token)
	if !ok {
		return nil, ErrUnauthorized
	}
	if !hmac.Equal([]byte(signature), []byte(a.sign(payload))) {
		return nil, ErrUnauthorized
	}

	rawPayload, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		return nil, ErrUnauthorized
	}

	var decoded struct {
		PrincipalID uuid.UUID `json:"principal_id"`
		UserID      string    `json:"user_id"`
		Permissions []string  `json:"permissions"`
		ExpiresAt   int64     `json:"expires_at"`
	}
	if err := json.Unmarshal(rawPayload, &decoded); err != nil {
		return nil, ErrUnauthorized
	}

	claims := &Claims{
		PrincipalID: decoded.PrincipalID,
		UserID:      decoded.UserID,
		Permissions: decoded.Permissions,
		ExpiresAt:   time.Unix(decoded.ExpiresAt, 0),
	}
	if a.now().After(claims.ExpiresAt) {
		return nil, ErrUnauthorized
	}

	return claims, nil
}

func (a *Authenticator) sign(payload string) string {
	mac := hmac.New(sha256.New, a.secret)
	_, _ = mac.Write([]byte(payload))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func (a *Authenticator) issueTokenFromSnapshot(snapshot *ClaimsSnapshot) (string, error) {
	if snapshot == nil {
		return "", ErrUnauthorized
	}

	claims := claimsFromSnapshot(snapshot, a.now().Add(a.ttl))
	payload, err := json.Marshal(struct {
		PrincipalID uuid.UUID `json:"principal_id"`
		UserID      string    `json:"user_id"`
		Permissions []string  `json:"permissions"`
		ExpiresAt   int64     `json:"expires_at"`
	}{
		PrincipalID: claims.PrincipalID,
		UserID:      claims.UserID,
		Permissions: claims.Permissions,
		ExpiresAt:   claims.ExpiresAt.Unix(),
	})
	if err != nil {
		return "", err
	}

	encodedPayload := base64.RawURLEncoding.EncodeToString(payload)
	signature := a.sign(encodedPayload)
	return encodedPayload + "." + signature, nil
}

func splitToken(token string) (payload string, signature string, ok bool) {
	for i := 0; i < len(token); i++ {
		if token[i] == '.' {
			return token[:i], token[i+1:], token[:i] != "" && token[i+1:] != ""
		}
	}
	return "", "", false
}

func claimsFromSnapshot(snapshot *ClaimsSnapshot, expiresAt time.Time) *Claims {
	if snapshot == nil {
		return nil
	}
	return &Claims{
		PrincipalID: snapshot.PrincipalID,
		UserID:      snapshot.UserID,
		Permissions: append([]string(nil), snapshot.Permissions...),
		ExpiresAt:   expiresAt,
	}
}
