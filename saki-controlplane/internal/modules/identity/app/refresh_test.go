package app

import (
	"context"
	"errors"
	"testing"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

func TestRefreshUseCaseRotatesSessionAndIssuesAccessToken(t *testing.T) {
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000203")
	store := &fakeRefreshAccountStore{
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
		},
	}
	refreshSessions := &fakeRefreshSessionManager{
		rotate: &RefreshSessionIssue{
			RefreshToken: "rotated-refresh-token",
			Session:      newTestRefreshSession(principalID),
		},
	}
	accessTokens := &fakeIdentityAccessTokenIssuer{token: "access-token"}

	useCase := NewRefreshUseCase(store, accessTokens, refreshSessions, 0)
	session, err := useCase.Execute(context.Background(), RefreshCommand{
		RefreshToken: "current-refresh-token",
	})
	if err != nil {
		t.Fatalf("refresh auth session: %v", err)
	}

	if session.AccessToken != "access-token" || session.RefreshToken != "rotated-refresh-token" {
		t.Fatalf("unexpected session tokens: %+v", session)
	}
	if session.ExpiresIn != int64((10 * time.Minute).Seconds()) {
		t.Fatalf("unexpected default access token ttl: %+v", session)
	}
	if session.User.PrincipalID != principalID || session.User.Email != "user@example.com" {
		t.Fatalf("unexpected session user: %+v", session.User)
	}
	if len(accessTokens.calls) != 1 || accessTokens.calls[0] != "user@example.com" {
		t.Fatalf("expected access token issued for account email, got %+v", accessTokens.calls)
	}
	if len(refreshSessions.rotateCalls) != 1 || refreshSessions.rotateCalls[0].RefreshToken != "current-refresh-token" {
		t.Fatalf("expected refresh usecase to rotate submitted token, got %+v", refreshSessions.rotateCalls)
	}
}

func TestRefreshUseCasePropagatesReplayDetection(t *testing.T) {
	refreshSessions := &fakeRefreshSessionManager{
		rotateErr: ErrRefreshSessionReplayDetected,
	}
	useCase := NewRefreshUseCase(&fakeRefreshAccountStore{}, &fakeIdentityAccessTokenIssuer{token: "unused"}, refreshSessions, time.Hour)

	_, err := useCase.Execute(context.Background(), RefreshCommand{
		RefreshToken: "replayed-refresh-token",
	})
	if !errors.Is(err, ErrRefreshSessionReplayDetected) {
		t.Fatalf("expected replay error, got %v", err)
	}
}

type fakeRefreshAccountStore struct {
	account    *AuthAccount
	accountErr error
	calls      []uuid.UUID
}

func (f *fakeRefreshAccountStore) FindAccountByPrincipalID(_ context.Context, principalID uuid.UUID) (*AuthAccount, error) {
	f.calls = append(f.calls, principalID)
	if f.accountErr != nil {
		return nil, f.accountErr
	}
	if f.account == nil {
		return nil, nil
	}
	copy := *f.account
	return &copy, nil
}
