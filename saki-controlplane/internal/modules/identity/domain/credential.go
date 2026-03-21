package domain

import (
	"time"

	"github.com/google/uuid"
)

const (
	CredentialProviderLocalPassword = "local_password"
	PasswordSchemeArgon2id          = "password_argon2id"
)

type PasswordCredential struct {
	ID                 uuid.UUID
	PrincipalID        uuid.UUID
	Provider           string
	Scheme             string
	PasswordHash       string
	MustChangePassword bool
	PasswordChangedAt  *time.Time
	CreatedAt          time.Time
	UpdatedAt          time.Time
}
