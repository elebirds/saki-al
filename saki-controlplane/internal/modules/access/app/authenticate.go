package app

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"time"
)

var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrForbidden    = errors.New("forbidden")
)

type Claims struct {
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
}

func NewAuthenticator(secret string, ttl time.Duration) *Authenticator {
	return &Authenticator{
		secret: []byte(secret),
		ttl:    ttl,
		now:    time.Now,
	}
}

func (a *Authenticator) IssueToken(userID string, permissions []string) (string, error) {
	payload, err := json.Marshal(struct {
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
		ExpiresAt   int64    `json:"expires_at"`
	}{
		UserID:      userID,
		Permissions: permissions,
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
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
		ExpiresAt   int64    `json:"expires_at"`
	}
	if err := json.Unmarshal(rawPayload, &decoded); err != nil {
		return nil, ErrUnauthorized
	}

	claims := &Claims{
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
