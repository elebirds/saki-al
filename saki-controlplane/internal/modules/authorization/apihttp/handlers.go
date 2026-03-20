package apihttp

import (
	"context"
	"slices"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type ListRolesExecutor interface {
	Execute(ctx context.Context, input authorizationapp.ListRolesInput) (*authorizationapp.RoleListResult, error)
}

type PermissionCatalogExecutor interface {
	Execute(ctx context.Context) (*authorizationapp.PermissionCatalog, error)
}

type UserSystemRolesExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID) ([]authorizationapp.UserSystemRoleBindingView, error)
}

type HandlersDeps struct {
	ListRoles         ListRolesExecutor
	PermissionCatalog PermissionCatalogExecutor
	UserSystemRoles   UserSystemRolesExecutor
}

type Handlers struct {
	listRoles         ListRolesExecutor
	permissionCatalog PermissionCatalogExecutor
	userSystemRoles   UserSystemRolesExecutor
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		listRoles:         deps.ListRoles,
		permissionCatalog: deps.PermissionCatalog,
		userSystemRoles:   deps.UserSystemRoles,
	}
}

func (h *Handlers) ListRoles(ctx context.Context, params openapi.ListRolesParams) (*openapi.RoleListResponse, error) {
	if h == nil || h.listRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read", "role:read", "role:read:all"); err != nil {
		return nil, err
	}

	page, _ := params.Page.Get()
	limit, _ := params.Limit.Get()
	roleType, _ := params.Type.Get()

	result, err := h.listRoles.Execute(ctx, authorizationapp.ListRolesInput{
		Page:  int(page),
		Limit: int(limit),
		Type:  string(roleType),
	})
	if err != nil {
		return nil, err
	}

	items := make([]openapi.RoleListItem, 0, len(result.Items))
	for _, item := range result.Items {
		items = append(items, mapRole(item))
	}
	return &openapi.RoleListResponse{
		Items:   items,
		Total:   int32(result.Total),
		Offset:  int32(result.Offset),
		Limit:   int32(result.Limit),
		Size:    int32(result.Size),
		HasMore: result.HasMore,
	}, nil
}

func (h *Handlers) GetRolePermissionCatalog(ctx context.Context) (*openapi.PermissionCatalogResponse, error) {
	return h.getPermissionCatalog(ctx)
}

func (h *Handlers) GetSystemPermissions(ctx context.Context) (*openapi.SystemPermissionsResponse, error) {
	if h == nil || h.userSystemRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	claims, err := requireAnyPermission(ctx)
	if err != nil {
		return nil, err
	}

	roleBindings, err := h.userSystemRoles.Execute(ctx, claims.PrincipalID)
	if err != nil {
		return nil, err
	}

	roles := make([]openapi.UserRoleInfo, 0, len(roleBindings))
	isSuperAdmin := false
	for _, item := range roleBindings {
		roles = append(roles, openapi.UserRoleInfo{
			ID:          item.RoleID,
			Name:        item.RoleName,
			DisplayName: item.RoleDisplayName,
			Color:       item.RoleColor,
			IsSupremo:   item.RoleIsSupremo,
		})
		if item.RoleName == "super_admin" {
			isSuperAdmin = true
		}
	}

	return &openapi.SystemPermissionsResponse{
		UserID:       claims.UserID,
		SystemRoles:  roles,
		Permissions:  authorizationdomain.ExpandedPermissionsForTransport(claims.Permissions),
		IsSuperAdmin: isSuperAdmin,
	}, nil
}

func (h *Handlers) ListUserSystemRoles(ctx context.Context, params openapi.ListUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	return h.listUserSystemRoles(ctx, params.UserID)
}

func (h *Handlers) ListUserSystemRolesLegacy(ctx context.Context, params openapi.ListUserSystemRolesLegacyParams) ([]openapi.UserSystemRoleBinding, error) {
	return h.listUserSystemRoles(ctx, params.UserID)
}

func (h *Handlers) getPermissionCatalog(ctx context.Context) (*openapi.PermissionCatalogResponse, error) {
	if h == nil || h.permissionCatalog == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read", "role:read", "role:read:all"); err != nil {
		return nil, err
	}

	catalog, err := h.permissionCatalog.Execute(ctx)
	if err != nil {
		return nil, err
	}
	return &openapi.PermissionCatalogResponse{
		AllPermissions:      authorizationdomain.ExpandedPermissionsForTransport(catalog.AllPermissions),
		SystemPermissions:   authorizationdomain.ExpandedPermissionsForTransport(catalog.SystemPermissions),
		ResourcePermissions: authorizationdomain.ExpandedPermissionsForTransport(catalog.ResourcePermissions),
	}, nil
}

func (h *Handlers) listUserSystemRoles(ctx context.Context, rawUserID string) ([]openapi.UserSystemRoleBinding, error) {
	if h == nil || h.userSystemRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	// 关键设计：这里同时接受新旧权限别名，是因为“查看用户系统角色绑定”仍处于迁移窗口。
	// 服务端先兼容门槛，后续再统一到新的 plural 语义，避免前后端切换被权限命名差异卡住。
	if _, err := requireAnyPermission(ctx, "roles:read", "users:read", "role:read", "role:read:all", "user:role_read", "user:role_read:all"); err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(rawUserID)
	if err != nil {
		return nil, accessapp.ErrForbidden
	}

	result, err := h.userSystemRoles.Execute(ctx, principalID)
	if err != nil {
		return nil, err
	}

	items := make([]openapi.UserSystemRoleBinding, 0, len(result))
	for _, item := range result {
		items = append(items, openapi.UserSystemRoleBinding{
			ID:              item.ID,
			UserID:          item.UserID,
			RoleID:          item.RoleID,
			RoleName:        item.RoleName,
			RoleDisplayName: item.RoleDisplayName,
			AssignedAt:      item.AssignedAt,
		})
	}
	return items, nil
}

func mapRole(item authorizationapp.RoleView) openapi.RoleListItem {
	result := openapi.RoleListItem{
		ID:          item.ID,
		Name:        item.Name,
		DisplayName: item.DisplayName,
		Type:        item.Type,
		BuiltIn:     item.BuiltIn,
		Mutable:     item.Mutable,
		Color:       item.Color,
		IsSupremo:   item.IsSupremo,
		SortOrder:   int32(item.SortOrder),
		IsSystem:    item.IsSystem,
		Permissions: make([]openapi.RolePermissionEntry, 0, len(item.Permissions)),
		CreatedAt:   item.CreatedAt,
		UpdatedAt:   item.UpdatedAt,
	}
	if item.Description != "" {
		result.Description.SetTo(item.Description)
	}
	for _, permission := range item.Permissions {
		result.Permissions = append(result.Permissions, openapi.RolePermissionEntry{
			Permission: permission.Permission,
		})
	}
	return result
}

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}
	if len(permissions) == 0 {
		return claims, nil
	}
	for _, permission := range permissions {
		if slices.Contains(claims.Permissions, permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
}
