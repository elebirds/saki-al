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

	if err := a.collectSystemPermissions(ctx, principalID, resolved); err != nil {
		return nil, err
	}

	if resource.Type != "" && resource.ID != uuid.Nil {
		if err := a.collectMatchingMembershipPermissions(ctx, principalID, resource, resolved); err != nil {
			return nil, err
		}
	}

	return flattenResolvedPermissions(resolved), nil
}

// 迁移期 access auth shell 需要一个扁平权限快照，避免在 handler 或 middleware 内部重复拼权限。
// 正式的人类控制面授权边界仍然由 authorization.Authorizer 负责，access 这里只消费快照。
func (a *Authorizer) ResolvePermissionSnapshot(ctx context.Context, principalID uuid.UUID) ([]string, error) {
	resolved := map[string]struct{}{}

	if err := a.collectSystemPermissions(ctx, principalID, resolved); err != nil {
		return nil, err
	}
	if err := a.collectAllMembershipPermissions(ctx, principalID, resolved); err != nil {
		return nil, err
	}

	return flattenResolvedPermissions(resolved), nil
}

func (a *Authorizer) collectSystemPermissions(ctx context.Context, principalID uuid.UUID, resolved map[string]struct{}) error {
	systemBindings, err := a.store.ListSystemBindingsByPrincipal(ctx, principalID)
	if err != nil {
		return err
	}
	for _, binding := range systemBindings {
		if err := a.collectRolePermissions(ctx, resolved, binding.RoleID); err != nil {
			return err
		}
	}
	return nil
}

func (a *Authorizer) collectMatchingMembershipPermissions(ctx context.Context, principalID uuid.UUID, resource authorizationdomain.ResourceRef, resolved map[string]struct{}) error {
	memberships, err := a.store.ListMembershipsByPrincipal(ctx, principalID)
	if err != nil {
		return err
	}
	for _, membership := range memberships {
		if !membership.Matches(resource) {
			continue
		}
		if err := a.collectRolePermissions(ctx, resolved, membership.RoleID); err != nil {
			return err
		}
	}
	return nil
}

func (a *Authorizer) collectAllMembershipPermissions(ctx context.Context, principalID uuid.UUID, resolved map[string]struct{}) error {
	memberships, err := a.store.ListMembershipsByPrincipal(ctx, principalID)
	if err != nil {
		return err
	}
	for _, membership := range memberships {
		if err := a.collectRolePermissions(ctx, resolved, membership.RoleID); err != nil {
			return err
		}
	}
	return nil
}

func flattenResolvedPermissions(resolved map[string]struct{}) []string {
	permissions := make([]string, 0, len(resolved))
	for permission := range resolved {
		permissions = append(permissions, permission)
	}
	sort.Strings(permissions)
	return permissions
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
