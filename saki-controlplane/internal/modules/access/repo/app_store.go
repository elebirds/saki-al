package repo

import (
	"context"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	identityrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/repo"
	"github.com/google/uuid"
)

type ClaimsStoreDeps struct {
	IdentityPrincipals *identityrepo.PrincipalRepo
	IdentityUsers      *identityrepo.UserRepo
	Authorizer         *authorizationapp.Authorizer
}

type ClaimsStore struct {
	identityPrincipals *identityrepo.PrincipalRepo
	identityUsers      *identityrepo.UserRepo
	authorizer         *authorizationapp.Authorizer
}

var _ accessapp.ClaimsStore = (*ClaimsStore)(nil)

func NewClaimsStore(deps ClaimsStoreDeps) *ClaimsStore {
	return &ClaimsStore{
		identityPrincipals: deps.IdentityPrincipals,
		identityUsers:      deps.IdentityUsers,
		authorizer:         deps.Authorizer,
	}
}

func (s *ClaimsStore) LoadClaimsByUserID(ctx context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	// 关键设计：public API 已切到最新无兼容语义后，claims 主路径只认 identity 用户，
	// 不再回退到 legacy bootstrap principal，避免旧 token 继续穿透到新的人类控制面接口。
	return s.loadIdentityClaimsByUserID(ctx, userID)
}

func (s *ClaimsStore) LoadClaimsByPrincipalID(ctx context.Context, principalID uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	return s.loadIdentityClaimsByPrincipalID(ctx, principalID)
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
