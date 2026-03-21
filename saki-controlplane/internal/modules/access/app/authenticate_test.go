package app

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

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
		loadByIdentifierErr: map[string]error{
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
		claimsByIdentifier: map[string]*ClaimsSnapshot{
			"user-1": {
				PrincipalID: principalID,
				Identifier:  "user-1",
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
	if claims.Identifier != "user-1" {
		t.Fatalf("expected user-1 claims, got %+v", claims)
	}
	expected := []string{"imports:read", "projects:read"}
	if !slices.Equal(claims.Permissions, expected) {
		t.Fatalf("expected aggregate-loaded permissions %v, got %+v", expected, claims)
	}
	if store.loadByIdentifierCalls != 1 {
		t.Fatalf("expected one aggregate identifier lookup, got %d", store.loadByIdentifierCalls)
	}
	if store.loadByPrincipalCalls != 0 {
		t.Fatalf("expected no principal reload during issue, got %d", store.loadByPrincipalCalls)
	}
}

type fakeStore struct {
	claimsByIdentifier   map[string]*ClaimsSnapshot
	claimsByPrincipalID  map[uuid.UUID]*ClaimsSnapshot
	loadByIdentifierErr  map[string]error
	loadByPrincipalErr   map[uuid.UUID]error
	loadByIdentifierCalls int
	loadByPrincipalCalls int
}

func (s *fakeStore) LoadClaimsByIdentifier(_ context.Context, identifier string) (*ClaimsSnapshot, error) {
	s.loadByIdentifierCalls++
	if s.loadByIdentifierErr != nil {
		if err := s.loadByIdentifierErr[identifier]; err != nil {
			return nil, err
		}
	}
	if s.claimsByIdentifier == nil {
		return nil, nil
	}
	claims := s.claimsByIdentifier[identifier]
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

func cloneClaims(claims *ClaimsSnapshot) *ClaimsSnapshot {
	if claims == nil {
		return nil
	}
	cloned := *claims
	cloned.Permissions = append([]string(nil), claims.Permissions...)
	return &cloned
}
