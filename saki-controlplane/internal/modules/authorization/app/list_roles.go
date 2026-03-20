package app

import (
	"context"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

type RoleListStore interface {
	CountByScope(ctx context.Context, scopeKind authorizationdomain.RoleScopeKind) (int, error)
	ListByScope(ctx context.Context, scopeKind authorizationdomain.RoleScopeKind, offset int, limit int) ([]authorizationdomain.Role, error)
	ListPermissions(ctx context.Context, roleID uuid.UUID) ([]string, error)
}

type ListRolesInput struct {
	Page  int
	Limit int
	Type  string
}

type ListRolesUseCase struct {
	store RoleListStore
}

func NewListRolesUseCase(store RoleListStore) *ListRolesUseCase {
	return &ListRolesUseCase{store: store}
}

func (u *ListRolesUseCase) Execute(ctx context.Context, input ListRolesInput) (*RoleListResult, error) {
	_, limit, offset := normalizePage(input.Page, input.Limit)
	scopeKind := normalizeRoleScope(input.Type)

	total, err := u.store.CountByScope(ctx, scopeKind)
	if err != nil {
		return nil, err
	}
	roles, err := u.store.ListByScope(ctx, scopeKind, offset, limit)
	if err != nil {
		return nil, err
	}
	if roles == nil {
		return &RoleListResult{
			Items:   nil,
			Total:   0,
			Offset:  offset,
			Limit:   limit,
			Size:    0,
			HasMore: false,
		}, nil
	}

	items := make([]RoleView, 0, len(roles))
	for _, role := range roles {
		permissions, err := u.store.ListPermissions(ctx, role.ID)
		if err != nil {
			return nil, err
		}

		expandedPermissions := make([]RolePermissionView, 0, len(permissions))
		for _, permission := range permissions {
			expandedPermissions = append(expandedPermissions, RolePermissionView{Permission: permission})
		}

		items = append(items, RoleView{
			ID:          role.ID.String(),
			Name:        role.Name,
			DisplayName: role.DisplayName,
			Description: role.Description,
			Type:        string(role.ScopeKind),
			BuiltIn:     role.BuiltIn,
			Mutable:     role.Mutable,
			Color:       role.Color,
			IsSupremo:   role.IsSupremo,
			SortOrder:   role.SortOrder,
			IsSystem:    role.ScopeKind == authorizationdomain.RoleScopeSystem,
			Permissions: expandedPermissions,
			CreatedAt:   role.CreatedAt,
			UpdatedAt:   role.UpdatedAt,
		})
	}

	return &RoleListResult{
		Items:   items,
		Total:   total,
		Offset:  offset,
		Limit:   limit,
		Size:    len(items),
		HasMore: offset+len(items) < total,
	}, nil
}

func normalizeRoleScope(scope string) authorizationdomain.RoleScopeKind {
	switch scope {
	case string(authorizationdomain.RoleScopeSystem):
		return authorizationdomain.RoleScopeSystem
	case string(authorizationdomain.RoleScopeResource):
		return authorizationdomain.RoleScopeResource
	default:
		return ""
	}
}
