package app

import (
	"context"
	"net/netip"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestInitializeSystemUseCaseCreatesInitialAdminSession(t *testing.T) {
	now := time.Date(2026, 3, 20, 13, 30, 0, 0, time.UTC)
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000001301")
	store := &fakeInitializeSystemStore{
		result: &InitializeSystemResult{
			PrincipalID: principalID,
			Email:       "admin@example.com",
			FullName:    "Initial Admin",
		},
	}
	accessTokens := &fakeAccessTokenIssuer{token: "access-token"}
	refreshTokens := &fakeOpaqueTokenIssuer{
		token: "refresh-token",
		hash:  "refresh-hash",
	}
	useCase := NewInitializeSystemUseCase(store, accessTokens, refreshTokens, time.Hour)
	useCase.now = func() time.Time { return now }

	ip := netip.MustParseAddr("127.0.0.1")
	session, err := useCase.Execute(t.Context(), InitializeSystemCommand{
		Email:     "ADMIN@example.com",
		Password:  "super-secret",
		FullName:  "Initial Admin",
		UserAgent: "apitest",
		IPAddress: &ip,
	})
	if err != nil {
		t.Fatalf("execute initialize system: %v", err)
	}

	if session.AccessToken != "access-token" || session.RefreshToken != "refresh-token" {
		t.Fatalf("unexpected session tokens: %+v", session)
	}
	if session.ExpiresIn != int64(time.Hour.Seconds()) {
		t.Fatalf("unexpected access token ttl: %+v", session)
	}
	if session.User.PrincipalID != principalID || session.User.Email != "admin@example.com" {
		t.Fatalf("unexpected initialized user: %+v", session.User)
	}
	if len(accessTokens.calls) != 1 || accessTokens.calls[0] != "admin@example.com" {
		t.Fatalf("expected access token to use persisted email, got %+v", accessTokens.calls)
	}
	if len(store.calls) != 1 {
		t.Fatalf("expected one store call, got %+v", store.calls)
	}
	call := store.calls[0]
	if call.PasswordHash == "" || call.PasswordHash == "super-secret" {
		t.Fatalf("expected password to be hashed before store call, got %+v", call)
	}
	if call.RefreshTokenHash != "refresh-hash" {
		t.Fatalf("unexpected refresh token hash: %+v", call)
	}
	if call.IPAddress == nil || *call.IPAddress != ip {
		t.Fatalf("unexpected ip address: %+v", call)
	}
	if !call.RefreshExpiresAt.Equal(now.Add(DefaultRefreshSessionTTL)) {
		t.Fatalf("unexpected refresh expiry: %+v", call)
	}
}

func TestInitializeSystemUseCasePropagatesAlreadyInitialized(t *testing.T) {
	useCase := NewInitializeSystemUseCase(
		&fakeInitializeSystemStore{err: ErrAlreadyInitialized},
		&fakeAccessTokenIssuer{token: "unused"},
		&fakeOpaqueTokenIssuer{token: "unused", hash: "unused"},
		30*time.Minute,
	)

	_, err := useCase.Execute(t.Context(), InitializeSystemCommand{
		Email:    "admin@example.com",
		Password: "secret",
		FullName: "Admin",
	})
	if err == nil {
		t.Fatal("expected already initialized to fail")
	}
}

func TestInitializeSystemUseCaseDefaultsAccessTokenTTLToTenMinutes(t *testing.T) {
	useCase := NewInitializeSystemUseCase(
		&fakeInitializeSystemStore{
			result: &InitializeSystemResult{
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000001302"),
				Email:       "admin@example.com",
				FullName:    "Initial Admin",
			},
		},
		&fakeAccessTokenIssuer{token: "access-token"},
		&fakeOpaqueTokenIssuer{token: "refresh-token", hash: "refresh-hash"},
		0,
	)

	session, err := useCase.Execute(t.Context(), InitializeSystemCommand{
		Email:    "admin@example.com",
		Password: "secret",
		FullName: "Initial Admin",
	})
	if err != nil {
		t.Fatalf("execute initialize system: %v", err)
	}
	if session.ExpiresIn != int64((10 * time.Minute).Seconds()) {
		t.Fatalf("unexpected default access ttl: %+v", session)
	}
}

type fakeInitializeSystemStore struct {
	result *InitializeSystemResult
	err    error
	calls  []InitializeSystemParams
}

func (f *fakeInitializeSystemStore) InitializeSystem(_ context.Context, params InitializeSystemParams) (*InitializeSystemResult, error) {
	f.calls = append(f.calls, params)
	if f.err != nil {
		return nil, f.err
	}
	if f.result == nil {
		return nil, nil
	}
	copy := *f.result
	return &copy, nil
}

type fakeAccessTokenIssuer struct {
	token string
	err   error
	calls []string
}

func (f *fakeAccessTokenIssuer) IssueTokenContext(_ context.Context, userID string) (string, error) {
	f.calls = append(f.calls, userID)
	if f.err != nil {
		return "", f.err
	}
	return f.token, nil
}

type fakeOpaqueTokenIssuer struct {
	token string
	hash  string
	err   error
}

func (f *fakeOpaqueTokenIssuer) IssueOpaqueToken() (string, string, error) {
	if f.err != nil {
		return "", "", f.err
	}
	return f.token, f.hash, nil
}
