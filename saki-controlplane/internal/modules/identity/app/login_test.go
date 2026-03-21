package app

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"testing"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

func TestLoginUseCaseRejectsLegacyFrontendCredentialScheme(t *testing.T) {
	hasher := NewPasswordHasher()
	legacyDigest := sha256.Sum256([]byte("secret-pass"))
	legacyHash, err := hasher.Hash(hex.EncodeToString(legacyDigest[:]))
	if err != nil {
		t.Fatalf("hash legacy password: %v", err)
	}

	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000201")
	store := &fakeLoginStore{
		account: &AuthAccount{
			Principal: identitydomain.Principal{
				ID:     principalID,
				Kind:   identitydomain.PrincipalKindHumanUser,
				Status: identitydomain.PrincipalStatusActive,
			},
			User: identitydomain.User{
				PrincipalID: principalID,
				Email:       "user@example.com",
				FullName:    testStringPtr("User"),
				State:       identitydomain.UserStateActive,
			},
			Credentials: []identitydomain.PasswordCredential{
				{
					PrincipalID:  principalID,
					Provider:     identitydomain.CredentialProviderLocalPassword,
					Scheme:       "legacy_frontend_sha256_argon2",
					PasswordHash: legacyHash,
				},
			},
		},
	}
	refreshSessions := &fakeRefreshSessionManager{
		issue: &RefreshSessionIssue{
			RefreshToken: "refresh-token",
			Session:      newTestRefreshSession(principalID),
		},
	}
	accessTokens := &fakeIdentityAccessTokenIssuer{token: "access-token"}

	useCase := NewLoginUseCase(store, accessTokens, refreshSessions, nil, 0)
	_, err = useCase.Execute(context.Background(), LoginCommand{
		Identifier: "user@example.com",
		Password:   "secret-pass",
	})
	if !errors.Is(err, ErrInvalidCredentials) {
		t.Fatalf("expected invalid credentials for removed legacy scheme, got %v", err)
	}
	if len(accessTokens.calls) != 0 {
		t.Fatalf("expected legacy credential login not to issue access token, got %+v", accessTokens.calls)
	}
	if len(refreshSessions.issueCalls) != 0 {
		t.Fatalf("expected legacy credential login not to issue refresh session, got %+v", refreshSessions.issueCalls)
	}
}

func TestLoginUseCaseRejectsInvalidPassword(t *testing.T) {
	hasher := NewPasswordHasher()
	hash, err := hasher.Hash("correct-password")
	if err != nil {
		t.Fatalf("hash password: %v", err)
	}

	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000202")
	store := &fakeLoginStore{
		account: &AuthAccount{
			Principal: identitydomain.Principal{
				ID:     principalID,
				Kind:   identitydomain.PrincipalKindHumanUser,
				Status: identitydomain.PrincipalStatusActive,
			},
			User: identitydomain.User{
				PrincipalID: principalID,
				Email:       "user@example.com",
				State:       identitydomain.UserStateActive,
			},
			Credentials: []identitydomain.PasswordCredential{
				{
					PrincipalID:  principalID,
					Provider:     identitydomain.CredentialProviderLocalPassword,
					Scheme:       identitydomain.PasswordSchemeArgon2id,
					PasswordHash: hash,
				},
			},
		},
	}
	refreshSessions := &fakeRefreshSessionManager{
		issue: &RefreshSessionIssue{
			RefreshToken: "refresh-token",
			Session:      newTestRefreshSession(principalID),
		},
	}
	accessTokens := &fakeIdentityAccessTokenIssuer{token: "access-token"}

	useCase := NewLoginUseCase(store, accessTokens, refreshSessions, nil, 15*time.Minute)
	_, err = useCase.Execute(context.Background(), LoginCommand{
		Identifier: "user@example.com",
		Password:   "wrong-password",
	})
	if !errors.Is(err, ErrInvalidCredentials) {
		t.Fatalf("expected invalid credentials, got %v", err)
	}
	if len(accessTokens.calls) != 0 {
		t.Fatalf("expected invalid password not to issue access token, got %+v", accessTokens.calls)
	}
	if len(refreshSessions.issueCalls) != 0 {
		t.Fatalf("expected invalid password not to issue refresh session, got %+v", refreshSessions.issueCalls)
	}
}

type fakeLoginStore struct {
	account     *AuthAccount
	accountErr  error
	lookupCalls []string
}

func (f *fakeLoginStore) FindAccountByIdentifier(_ context.Context, identifier string) (*AuthAccount, error) {
	f.lookupCalls = append(f.lookupCalls, identifier)
	if f.accountErr != nil {
		return nil, f.accountErr
	}
	if f.account == nil {
		return nil, nil
	}
	copy := *f.account
	copy.Credentials = append([]identitydomain.PasswordCredential(nil), f.account.Credentials...)
	return &copy, nil
}
