package domain

import (
	"time"

	"github.com/google/uuid"
)

const (
	CredentialProviderLocalPassword          = "local_password"
	PasswordSchemeArgon2id                   = "password_argon2id"
	PasswordSchemeLegacyFrontendSHA256Argon2 = "legacy_frontend_sha256_argon2"
)

type PasswordCredential struct {
	ID           uuid.UUID
	PrincipalID  uuid.UUID
	Provider     string
	Scheme       string
	PasswordHash string
	CreatedAt    time.Time
	UpdatedAt    time.Time
}
