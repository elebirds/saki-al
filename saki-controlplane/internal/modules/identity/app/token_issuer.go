package app

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"io"
	"time"
)

type TokenIssuer struct {
	rand io.Reader
	now  func() time.Time
}

func NewTokenIssuer() *TokenIssuer {
	return &TokenIssuer{
		rand: rand.Reader,
		now:  time.Now,
	}
}

func (i *TokenIssuer) IssueOpaqueToken() (token string, tokenHash string, err error) {
	buf := make([]byte, 32)
	if _, err := io.ReadFull(i.rand, buf); err != nil {
		return "", "", err
	}

	token = base64.RawURLEncoding.EncodeToString(buf)
	return token, i.HashOpaqueToken(token), nil
}

func (i *TokenIssuer) HashOpaqueToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}
