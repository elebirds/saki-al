package repo

import (
	"context"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	identityrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/repo"
	"github.com/google/uuid"
)

type ClaimsStoreDeps struct {
	LegacyPrincipals   *PrincipalRepo
	IdentityPrincipals *identityrepo.PrincipalRepo
	IdentityUsers      *identityrepo.UserRepo
	Authorizer         *authorizationapp.Authorizer
}

type ClaimsStore struct {
	legacyPrincipals   *PrincipalRepo
	identityPrincipals *identityrepo.PrincipalRepo
	identityUsers      *identityrepo.UserRepo
	authorizer         *authorizationapp.Authorizer
}

type BootstrapStore struct {
	repo *PrincipalRepo
}

var _ accessapp.ClaimsStore = (*ClaimsStore)(nil)
var _ accessapp.BootstrapClaimsStore = (*ClaimsStore)(nil)
var _ accessapp.BootstrapStore = (*BootstrapStore)(nil)

func NewClaimsStore(deps ClaimsStoreDeps) *ClaimsStore {
	return &ClaimsStore{
		legacyPrincipals:   deps.LegacyPrincipals,
		identityPrincipals: deps.IdentityPrincipals,
		identityUsers:      deps.IdentityUsers,
		authorizer:         deps.Authorizer,
	}
}

func NewBootstrapStore(repo *PrincipalRepo) *BootstrapStore {
	return &BootstrapStore{repo: repo}
}

func (s *ClaimsStore) LoadClaimsByUserID(ctx context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	if claims, err := s.loadIdentityClaimsByUserID(ctx, userID); err != nil || claims != nil {
		return claims, err
	}
	return s.loadLegacyClaimsByUserID(ctx, userID)
}

func (s *ClaimsStore) LoadBootstrapClaimsByUserID(ctx context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	return s.loadLegacyClaimsByUserID(ctx, userID)
}

func (s *ClaimsStore) LoadClaimsByPrincipalID(ctx context.Context, principalID uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	if claims, err := s.loadIdentityClaimsByPrincipalID(ctx, principalID); err != nil || claims != nil {
		return claims, err
	}
	return s.loadLegacyClaimsByPrincipalID(ctx, principalID)
}

func (s *BootstrapStore) UpsertBootstrapPrincipal(ctx context.Context, spec accessapp.BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	principal, err := s.repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: accessdomain.SubjectTypeUser,
		SubjectKey:  spec.UserID,
		DisplayName: spec.DisplayName,
		Permissions: spec.Permissions,
	})
	if err != nil || principal == nil {
		return nil, err
	}
	return mapAppPrincipal(principal), nil
}

func (s *ClaimsStore) loadIdentityClaimsByUserID(ctx context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	if s.identityUsers == nil {
		return nil, nil
	}

	user, err := s.identityUsers.GetByEmail(ctx, userID)
	if err != nil || user == nil {
		return nil, err
	}

	return s.loadIdentityClaimsByPrincipalID(ctx, user.PrincipalID)
}

func (s *ClaimsStore) loadIdentityClaimsByPrincipalID(ctx context.Context, principalID uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	if s.identityPrincipals == nil || s.identityUsers == nil || s.authorizer == nil {
		return nil, nil
	}

	principal, err := s.identityPrincipals.GetByID(ctx, principalID)
	if err != nil || principal == nil {
		return nil, err
	}

	user, err := s.identityUsers.GetByPrincipalID(ctx, principalID)
	if err != nil || user == nil {
		return nil, err
	}

	if principal.IsDisabled() || user.State == identitydomain.UserStateDisabled {
		return nil, accessapp.ErrUnauthorized
	}

	permissions, err := s.authorizer.ResolvePermissionSnapshot(ctx, principalID)
	if err != nil {
		return nil, err
	}

	return &accessapp.ClaimsSnapshot{
		PrincipalID: principal.ID,
		UserID:      user.Email,
		Permissions: append([]string(nil), permissions...),
	}, nil
}

func (s *ClaimsStore) loadLegacyClaimsByUserID(ctx context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	if s.legacyPrincipals == nil {
		return nil, nil
	}

	principal, err := s.legacyPrincipals.GetBySubjectKey(ctx, accessdomain.SubjectTypeUser, userID)
	if err != nil || principal == nil {
		return nil, err
	}

	return s.loadLegacyClaimsFromPrincipal(ctx, principal)
}

func (s *ClaimsStore) loadLegacyClaimsByPrincipalID(ctx context.Context, principalID uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	if s.legacyPrincipals == nil {
		return nil, nil
	}

	principal, err := s.legacyPrincipals.GetByID(ctx, principalID)
	if err != nil || principal == nil {
		return nil, err
	}

	return s.loadLegacyClaimsFromPrincipal(ctx, principal)
}

func (s *ClaimsStore) loadLegacyClaimsFromPrincipal(ctx context.Context, principal *Principal) (*accessapp.ClaimsSnapshot, error) {
	if principal == nil {
		return nil, nil
	}
	if accessdomain.PrincipalStatus(principal.Status) == accessdomain.PrincipalStatusDisabled {
		return nil, accessapp.ErrUnauthorized
	}

	permissions, err := s.legacyPrincipals.ListPermissions(ctx, principal.ID)
	if err != nil {
		return nil, err
	}

	return &accessapp.ClaimsSnapshot{
		PrincipalID: principal.ID,
		UserID:      principal.SubjectKey,
		Permissions: append([]string(nil), permissions...),
	}, nil
}

func mapAppPrincipal(principal *Principal) *accessdomain.Principal {
	if principal == nil {
		return nil
	}
	return &accessdomain.Principal{
		ID:          principal.ID,
		SubjectType: principal.SubjectType,
		SubjectKey:  principal.SubjectKey,
		DisplayName: principal.DisplayName,
		Status:      accessdomain.PrincipalStatus(principal.Status),
	}
}
