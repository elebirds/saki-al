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
	store  Store
}

func NewAuthenticator(secret string, ttl time.Duration) *Authenticator {
	return &Authenticator{
		secret: []byte(secret),
		ttl:    ttl,
		now:    time.Now,
	}
}

func (a *Authenticator) WithStore(store Store) *Authenticator {
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

	principal, err := a.store.GetPrincipalByUserID(ctx, userID)
	if err != nil {
		return "", err
	}
	if principal == nil || principal.IsDisabled() {
		return "", ErrUnauthorized
	}

	resolvedPermissions, err := a.store.ListPermissions(ctx, principal.ID)
	if err != nil {
		return "", err
	}

	payload, err := json.Marshal(struct {
		PrincipalID uuid.UUID `json:"principal_id"`
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
		ExpiresAt   int64    `json:"expires_at"`
	}{
		PrincipalID: principal.ID,
		UserID:      userID,
		Permissions: resolvedPermissions,
		ExpiresAt:   a.now().Add(a.ttl).Unix(),
	})
	if err != nil {
		return "", err
	}

	encodedPayload := base64.RawURLEncoding.EncodeToString(payload)
	signature := a.sign(encodedPayload)
	return encodedPayload + "." + signature, nil
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
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
		ExpiresAt   int64    `json:"expires_at"`
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

func splitToken(token string) (payload string, signature string, ok bool) {
	for i := 0; i < len(token); i++ {
		if token[i] == '.' {
			return token[:i], token[i+1:], token[:i] != "" && token[i+1:] != ""
		}
	}
	return "", "", false
}
