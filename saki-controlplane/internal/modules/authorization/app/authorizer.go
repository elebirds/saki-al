package app

import (
	"context"
	"sort"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

type Store interface {
	ListSystemBindingsByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.SystemBinding, error)
	ListMembershipsByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.ResourceMembership, error)
	ListRolePermissions(ctx context.Context, roleID uuid.UUID) ([]string, error)
}

type Authorizer struct {
	store Store
}

func NewAuthorizer(store Store) *Authorizer {
	return &Authorizer{store: store}
}

func (a *Authorizer) ResolvePermissions(ctx context.Context, principalID uuid.UUID, resource authorizationdomain.ResourceRef) ([]string, error) {
	resolved := map[string]struct{}{}

	systemBindings, err := a.store.ListSystemBindingsByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}
	for _, binding := range systemBindings {
		if err := a.collectRolePermissions(ctx, resolved, binding.RoleID); err != nil {
			return nil, err
		}
	}

	if resource.Type != "" && resource.ID != uuid.Nil {
		memberships, err := a.store.ListMembershipsByPrincipal(ctx, principalID)
		if err != nil {
			return nil, err
		}
		for _, membership := range memberships {
			if !membership.Matches(resource) {
				continue
			}
			if err := a.collectRolePermissions(ctx, resolved, membership.RoleID); err != nil {
				return nil, err
			}
		}
	}

	permissions := make([]string, 0, len(resolved))
	for permission := range resolved {
		permissions = append(permissions, permission)
	}
	sort.Strings(permissions)
	return permissions, nil
}

func (a *Authorizer) collectRolePermissions(ctx context.Context, resolved map[string]struct{}, roleID uuid.UUID) error {
	permissions, err := a.store.ListRolePermissions(ctx, roleID)
	if err != nil {
		return err
	}
	for _, permission := range permissions {
		if !authorizationdomain.IsKnownPermission(permission) {
			continue
		}
		resolved[permission] = struct{}{}
	}
	return nil
}
