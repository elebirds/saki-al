package repo

import (
	"context"

	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

type AppStore struct {
	roles       *RoleRepo
	bindings    *BindingRepo
	memberships *MembershipRepo
}

var _ authorizationapp.Store = (*AppStore)(nil)

func NewAppStore(roles *RoleRepo, bindings *BindingRepo, memberships *MembershipRepo) *AppStore {
	return &AppStore{
		roles:       roles,
		bindings:    bindings,
		memberships: memberships,
	}
}

func (s *AppStore) ListSystemBindingsByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.SystemBinding, error) {
	return s.bindings.ListByPrincipal(ctx, principalID)
}

func (s *AppStore) ListMembershipsByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.ResourceMembership, error) {
	return s.memberships.ListByPrincipal(ctx, principalID)
}

func (s *AppStore) ListRolePermissions(ctx context.Context, roleID uuid.UUID) ([]string, error) {
	return s.roles.ListPermissions(ctx, roleID)
}
