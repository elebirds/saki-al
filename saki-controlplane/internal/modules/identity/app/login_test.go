package app

import (
	"context"
	"errors"
	"testing"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

func TestLoginUseCaseUpgradesLegacyCredentialAndIssuesSession(t *testing.T) {
	hasher := NewPasswordHasher()
	legacyHash, err := hasher.Hash(legacyFrontendPasswordDigest("secret-pass"))
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
					Scheme:       identitydomain.PasswordSchemeLegacyFrontendSHA256Argon2,
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
	session, err := useCase.Execute(context.Background(), LoginCommand{
		Identifier: "user@example.com",
		Password:   "secret-pass",
	})
	if err != nil {
		t.Fatalf("login: %v", err)
	}

	if session.AccessToken != "access-token" || session.RefreshToken != "refresh-token" {
		t.Fatalf("unexpected session tokens: %+v", session)
	}
	if session.ExpiresIn != int64((10 * time.Minute).Seconds()) {
		t.Fatalf("unexpected default access token ttl: %+v", session)
	}
	if session.User.PrincipalID != principalID || session.User.Email != "user@example.com" {
		t.Fatalf("unexpected session user: %+v", session.User)
	}
	if session.MustChangePassword {
		t.Fatalf("expected upgraded legacy credential not to force password change: %+v", session)
	}
	if len(accessTokens.calls) != 1 || accessTokens.calls[0] != "user@example.com" {
		t.Fatalf("expected access token issued for persisted email, got %+v", accessTokens.calls)
	}
	if len(refreshSessions.issueCalls) != 1 || refreshSessions.issueCalls[0].PrincipalID != principalID {
		t.Fatalf("expected refresh session issued for principal %s, got %+v", principalID, refreshSessions.issueCalls)
	}
	if store.upgrade == nil {
		t.Fatal("expected successful legacy login to upgrade credential scheme")
	}
	if store.upgrade.NewScheme != identitydomain.PasswordSchemeArgon2id {
		t.Fatalf("expected legacy credential upgraded to argon2id, got %+v", store.upgrade)
	}
	ok, err := hasher.Verify("secret-pass", store.upgrade.NewPasswordHash)
	if err != nil || !ok {
		t.Fatalf("expected upgraded hash to verify raw password, ok=%v err=%v", ok, err)
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
	if store.upgrade != nil {
		t.Fatalf("expected invalid password not to upgrade credential, got %+v", store.upgrade)
	}
}

type fakeLoginStore struct {
	account     *AuthAccount
	accountErr  error
	upgrade     *UpgradePasswordCredentialParams
	upgradeErr  error
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

func (f *fakeLoginStore) UpgradePasswordCredential(_ context.Context, params UpgradePasswordCredentialParams) error {
	f.upgrade = &params
	if f.upgradeErr != nil {
		return f.upgradeErr
	}
	return nil
}
