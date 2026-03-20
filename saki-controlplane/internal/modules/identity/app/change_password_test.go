package app

import (
	"context"
	"errors"
	"testing"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

func TestChangePasswordUseCaseRevokesExistingSessionsAndIssuesNewSession(t *testing.T) {
	now := time.Date(2026, 3, 20, 14, 0, 0, 0, time.UTC)
	hasher := NewPasswordHasher()
	oldHash, err := hasher.Hash("old-secret")
	if err != nil {
		t.Fatalf("hash old password: %v", err)
	}

	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000204")
	store := &fakeChangePasswordStore{
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
					PrincipalID:        principalID,
					Provider:           identitydomain.CredentialProviderLocalPassword,
					Scheme:             identitydomain.PasswordSchemeArgon2id,
					PasswordHash:       oldHash,
					MustChangePassword: true,
				},
			},
		},
		result: &PasswordMutationResult{
			User: identitydomain.User{
				PrincipalID: principalID,
				Email:       "user@example.com",
				FullName:    testStringPtr("User"),
				State:       identitydomain.UserStateActive,
			},
		},
	}
	accessTokens := &fakeIdentityAccessTokenIssuer{token: "access-token"}
	refreshTokens := &fakeIdentityOpaqueTokenIssuer{
		token: "refresh-token",
		hash:  "refresh-token-hash",
	}

	useCase := NewChangePasswordUseCase(store, accessTokens, refreshTokens, nil, 0)
	useCase.now = func() time.Time { return now }

	session, err := useCase.Execute(context.Background(), ChangePasswordCommand{
		PrincipalID:  principalID,
		OldPassword:  "old-secret",
		NewPassword:  "new-secret",
		UserAgent:    "apitest",
	})
	if err != nil {
		t.Fatalf("change password: %v", err)
	}

	if session.AccessToken != "access-token" || session.RefreshToken != "refresh-token" {
		t.Fatalf("unexpected auth session: %+v", session)
	}
	if session.ExpiresIn != int64((10 * time.Minute).Seconds()) {
		t.Fatalf("unexpected default access token ttl: %+v", session)
	}
	if session.MustChangePassword {
		t.Fatalf("expected change password to clear must_change_password, got %+v", session)
	}
	if len(accessTokens.calls) != 1 || accessTokens.calls[0] != "user@example.com" {
		t.Fatalf("expected access token issued for persisted email, got %+v", accessTokens.calls)
	}
	if store.change == nil {
		t.Fatal("expected change password store mutation to be called")
	}
	if store.change.RefreshTokenHash != "refresh-token-hash" {
		t.Fatalf("unexpected refresh token hash: %+v", store.change)
	}
	if got, want := store.change.RefreshExpiresAt, now.Add(DefaultRefreshSessionTTL); !got.Equal(want) {
		t.Fatalf("unexpected refresh expiry: got %s want %s", got, want)
	}
	if got, want := store.change.ChangedAt, now; !got.Equal(want) {
		t.Fatalf("unexpected changed_at: got %s want %s", got, want)
	}
	ok, err := hasher.Verify("new-secret", store.change.NewPasswordHash)
	if err != nil || !ok {
		t.Fatalf("expected new password hash to verify raw password, ok=%v err=%v", ok, err)
	}
}

func TestChangePasswordUseCaseRejectsInvalidCurrentPassword(t *testing.T) {
	hasher := NewPasswordHasher()
	oldHash, err := hasher.Hash("old-secret")
	if err != nil {
		t.Fatalf("hash old password: %v", err)
	}

	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000205")
	store := &fakeChangePasswordStore{
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
					PasswordHash: oldHash,
				},
			},
		},
	}

	useCase := NewChangePasswordUseCase(
		store,
		&fakeIdentityAccessTokenIssuer{token: "unused"},
		&fakeIdentityOpaqueTokenIssuer{token: "unused", hash: "unused"},
		nil,
		time.Hour,
	)

	_, err = useCase.Execute(context.Background(), ChangePasswordCommand{
		PrincipalID: principalID,
		OldPassword: "wrong-old-secret",
		NewPassword: "new-secret",
	})
	if !errors.Is(err, ErrInvalidCredentials) {
		t.Fatalf("expected invalid credentials for wrong current password, got %v", err)
	}
	if store.change != nil {
		t.Fatalf("expected wrong current password not to mutate credential, got %+v", store.change)
	}
}

type fakeChangePasswordStore struct {
	account    *AuthAccount
	accountErr error
	result     *PasswordMutationResult
	change     *ChangePasswordParams
	changeErr  error
	loadCalls  []uuid.UUID
}

func (f *fakeChangePasswordStore) FindAccountByPrincipalID(_ context.Context, principalID uuid.UUID) (*AuthAccount, error) {
	f.loadCalls = append(f.loadCalls, principalID)
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

func (f *fakeChangePasswordStore) ChangePassword(_ context.Context, params ChangePasswordParams) (*PasswordMutationResult, error) {
	f.change = &params
	if f.changeErr != nil {
		return nil, f.changeErr
	}
	if f.result == nil {
		return nil, nil
	}
	copy := *f.result
	return &copy, nil
}
