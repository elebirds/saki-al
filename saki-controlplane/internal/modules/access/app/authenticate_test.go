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
		loadByUserIDErr: map[string]error{
			"disabled-user": ErrUnauthorized,
		},
	})

	_, err := authenticator.IssueToken("disabled-user", nil)
	if !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("expected unauthorized for disabled principal, got %v", err)
	}
}

func TestIssueTokenUsesAggregateClaimsLoader(t *testing.T) {
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000222")
	store := &fakeStore{
		claimsByUserID: map[string]*ClaimsSnapshot{
			"user-1": {
				PrincipalID: principalID,
				UserID:      "user-1",
				Permissions: []string{"imports:read", "projects:read"},
			},
		},
	}
	authenticator := NewAuthenticator("test-secret", time.Hour).WithStore(store)

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
		t.Fatalf("expected aggregate-loaded permissions %v, got %+v", expected, claims)
	}
	if store.loadByUserIDCalls != 1 {
		t.Fatalf("expected one aggregate user lookup, got %d", store.loadByUserIDCalls)
	}
	if store.loadByPrincipalCalls != 0 {
		t.Fatalf("expected no principal reload during issue, got %d", store.loadByPrincipalCalls)
	}
}

func TestBootstrapSeedUpsertsConfiguredPrincipals(t *testing.T) {
	store := fakeStore{
		claimsByUserID:      map[string]*ClaimsSnapshot{},
		claimsByPrincipalID: map[uuid.UUID]*ClaimsSnapshot{},
		upsertedSubjects:    map[string]BootstrapPrincipalSpec{},
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
	claimsByUserID       map[string]*ClaimsSnapshot
	claimsByPrincipalID  map[uuid.UUID]*ClaimsSnapshot
	loadByUserIDErr      map[string]error
	loadByPrincipalErr   map[uuid.UUID]error
	upsertedSubjects     map[string]BootstrapPrincipalSpec
	loadByUserIDCalls    int
	loadByPrincipalCalls int
}

func (s *fakeStore) LoadClaimsByUserID(_ context.Context, userID string) (*ClaimsSnapshot, error) {
	s.loadByUserIDCalls++
	if s.loadByUserIDErr != nil {
		if err := s.loadByUserIDErr[userID]; err != nil {
			return nil, err
		}
	}
	if s.claimsByUserID == nil {
		return nil, nil
	}
	claims := s.claimsByUserID[userID]
	return cloneClaims(claims), nil
}

func (s *fakeStore) LoadClaimsByPrincipalID(_ context.Context, principalID uuid.UUID) (*ClaimsSnapshot, error) {
	s.loadByPrincipalCalls++
	if s.loadByPrincipalErr != nil {
		if err := s.loadByPrincipalErr[principalID]; err != nil {
			return nil, err
		}
	}
	if s.claimsByPrincipalID == nil {
		return nil, nil
	}
	claims := s.claimsByPrincipalID[principalID]
	return cloneClaims(claims), nil
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
	if s.claimsByUserID == nil {
		s.claimsByUserID = map[string]*ClaimsSnapshot{}
	}
	claims := &ClaimsSnapshot{
		PrincipalID: principal.ID,
		UserID:      spec.UserID,
		Permissions: append([]string(nil), spec.Permissions...),
	}
	s.claimsByUserID[spec.UserID] = claims
	if s.claimsByPrincipalID == nil {
		s.claimsByPrincipalID = map[uuid.UUID]*ClaimsSnapshot{}
	}
	s.claimsByPrincipalID[principal.ID] = cloneClaims(claims)
	return principal, nil
}

func cloneClaims(claims *ClaimsSnapshot) *ClaimsSnapshot {
	if claims == nil {
		return nil
	}
	cloned := *claims
	cloned.Permissions = append([]string(nil), claims.Permissions...)
	return &cloned
}
