package app

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	"github.com/google/uuid"
)

func TestIssueTokenRejectsUnknownPrincipal(t *testing.T) {
	authenticator := NewAuthenticator("test-secret", time.Hour).WithStore(&fakeStore{})

	_, err := authenticator.IssueToken("missing-user", nil)
	if !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("expected unauthorized for unknown principal, got %v", err)
	}
}

func TestIssueTokenRejectsDisabledPrincipal(t *testing.T) {
	authenticator := NewAuthenticator("test-secret", time.Hour).WithStore(&fakeStore{
		byUserID: map[string]*accessdomain.Principal{
			"disabled-user": {
				ID:          uuid.MustParse("00000000-0000-0000-0000-000000000111"),
				SubjectType: accessdomain.SubjectTypeUser,
				SubjectKey:  "disabled-user",
				DisplayName: "Disabled User",
				Status:      accessdomain.PrincipalStatusDisabled,
			},
		},
	})

	_, err := authenticator.IssueToken("disabled-user", nil)
	if !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("expected unauthorized for disabled principal, got %v", err)
	}
}

func TestIssueTokenUsesRepoBackedPermissions(t *testing.T) {
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000222")
	authenticator := NewAuthenticator("test-secret", time.Hour).WithStore(&fakeStore{
		byUserID: map[string]*accessdomain.Principal{
			"user-1": {
				ID:          principalID,
				SubjectType: accessdomain.SubjectTypeUser,
				SubjectKey:  "user-1",
				DisplayName: "User One",
				Status:      accessdomain.PrincipalStatusActive,
			},
		},
		permissionsByID: map[uuid.UUID][]string{
			principalID: {"imports:read", "projects:read"},
		},
	})

	token, err := authenticator.IssueToken("user-1", []string{"caller:write"})
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}

	claims, err := authenticator.ParseToken(token)
	if err != nil {
		t.Fatalf("parse token: %v", err)
	}

	if claims.PrincipalID != principalID {
		t.Fatalf("expected principal id %s, got %+v", principalID, claims)
	}
	if claims.UserID != "user-1" {
		t.Fatalf("expected user-1 claims, got %+v", claims)
	}
	expected := []string{"imports:read", "projects:read"}
	if !slices.Equal(claims.Permissions, expected) {
		t.Fatalf("expected repo-backed permissions %v, got %+v", expected, claims)
	}
}

func TestBootstrapSeedUpsertsConfiguredPrincipals(t *testing.T) {
	store := fakeStore{
		byUserID:         map[string]*accessdomain.Principal{},
		permissionsByID:  map[uuid.UUID][]string{},
		upsertedSubjects: map[string]BootstrapPrincipalSpec{},
	}
	useCase := NewBootstrapSeedUseCase(&store)

	err := useCase.Execute(context.Background(), []BootstrapPrincipalSpec{
		{
			UserID:      "seed-user",
			DisplayName: "Seed User",
			Permissions: []string{"projects:read", "projects:write"},
		},
	})
	if err != nil {
		t.Fatalf("execute bootstrap seed: %v", err)
	}

	spec, ok := store.upsertedSubjects["seed-user"]
	if !ok {
		t.Fatal("expected bootstrap seed to upsert user")
	}
	if spec.DisplayName != "Seed User" {
		t.Fatalf("unexpected bootstrap display name: %+v", spec)
	}
	if !slices.Equal(spec.Permissions, []string{"projects:read", "projects:write"}) {
		t.Fatalf("unexpected bootstrap permissions: %+v", spec)
	}
}

type fakeStore struct {
	byUserID         map[string]*accessdomain.Principal
	byID             map[uuid.UUID]*accessdomain.Principal
	permissionsByID  map[uuid.UUID][]string
	upsertedSubjects map[string]BootstrapPrincipalSpec
}

func (s fakeStore) GetPrincipalByUserID(_ context.Context, userID string) (*accessdomain.Principal, error) {
	if s.byUserID == nil {
		return nil, nil
	}
	return s.byUserID[userID], nil
}

func (s fakeStore) GetPrincipalByID(_ context.Context, principalID uuid.UUID) (*accessdomain.Principal, error) {
	if s.byID == nil {
		return nil, nil
	}
	return s.byID[principalID], nil
}

func (s fakeStore) ListPermissions(_ context.Context, principalID uuid.UUID) ([]string, error) {
	if s.permissionsByID == nil {
		return nil, nil
	}
	return append([]string(nil), s.permissionsByID[principalID]...), nil
}

func (s *fakeStore) UpsertBootstrapPrincipal(_ context.Context, spec BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	if s.upsertedSubjects == nil {
		s.upsertedSubjects = map[string]BootstrapPrincipalSpec{}
	}
	s.upsertedSubjects[spec.UserID] = spec

	principal := &accessdomain.Principal{
		ID:          uuid.New(),
		SubjectType: accessdomain.SubjectTypeUser,
		SubjectKey:  spec.UserID,
		DisplayName: spec.DisplayName,
		Status:      accessdomain.PrincipalStatusActive,
	}
	if s.byUserID == nil {
		s.byUserID = map[string]*accessdomain.Principal{}
	}
	s.byUserID[spec.UserID] = principal
	if s.permissionsByID == nil {
		s.permissionsByID = map[uuid.UUID][]string{}
	}
	s.permissionsByID[principal.ID] = append([]string(nil), spec.Permissions...)
	return principal, nil
}
