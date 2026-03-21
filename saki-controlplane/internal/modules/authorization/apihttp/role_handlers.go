package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

func (h *Handlers) ListRoles(ctx context.Context, params openapi.ListRolesParams) (*openapi.RoleListResponse, error) {
	if h == nil || h.listRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read"); err != nil {
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

func (h *Handlers) CreateRole(ctx context.Context, req *openapi.RoleCreateRequest) (*openapi.RoleListItem, error) {
	if h == nil || h.createRole == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:write"); err != nil {
		return nil, err
	}
	if req.GetName() == "" || req.GetDisplayName() == "" {
		return nil, authorizationapp.ErrInvalidRoleInput
	}

	description, hasDescription := req.GetDescription().Get()
	color, hasColor := req.GetColor().Get()
	role, err := h.createRole.Execute(ctx, authorizationapp.CreateRoleCommand{
		Name:        req.GetName(),
		DisplayName: req.GetDisplayName(),
		Description: optStringPtr(description, hasDescription),
		Color:       optStringPtr(color, hasColor),
		Permissions: req.GetPermissions(),
	})
	if err != nil {
		return nil, err
	}
	response := mapRole(*role)
	return &response, nil
}

func (h *Handlers) GetRole(ctx context.Context, params openapi.GetRoleParams) (*openapi.RoleListItem, error) {
	if h == nil || h.getRole == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read"); err != nil {
		return nil, err
	}

	roleID, err := uuid.Parse(params.RoleID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidRoleInput
	}
	role, err := h.getRole.Execute(ctx, roleID)
	if err != nil {
		return nil, err
	}
	response := mapRole(*role)
	return &response, nil
}

func (h *Handlers) UpdateRole(ctx context.Context, req *openapi.RoleUpdateRequest, params openapi.UpdateRoleParams) (*openapi.RoleListItem, error) {
	if h == nil || h.updateRole == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:write"); err != nil {
		return nil, err
	}

	roleID, err := uuid.Parse(params.RoleID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidRoleInput
	}
	displayName, hasDisplayName := req.GetDisplayName().Get()
	description, hasDescription := req.GetDescription().Get()
	color, hasColor := req.GetColor().Get()
	role, err := h.updateRole.Execute(ctx, authorizationapp.UpdateRoleCommand{
		RoleID:            roleID,
		DisplayName:       optStringPtr(displayName, hasDisplayName),
		ChangeDisplayName: hasDisplayName,
		Description:       optStringPtr(description, hasDescription),
		ChangeDescription: hasDescription,
		Color:             optStringPtr(color, hasColor),
		ChangeColor:       hasColor,
		Permissions:       req.GetPermissions(),
		ChangePermissions: req.Permissions != nil,
	})
	if err != nil {
		return nil, err
	}
	response := mapRole(*role)
	return &response, nil
}

func (h *Handlers) DeleteRole(ctx context.Context, params openapi.DeleteRoleParams) error {
	if h == nil || h.deleteRole == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:write"); err != nil {
		return err
	}

	roleID, err := uuid.Parse(params.RoleID)
	if err != nil {
		return authorizationapp.ErrInvalidRoleInput
	}
	return h.deleteRole.Execute(ctx, roleID)
}

func (h *Handlers) GetSystemPermissions(ctx context.Context) (*openapi.SystemPermissionsResponse, error) {
	if h == nil || h.permissionCatalog == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	// 关键设计：/permissions/system 返回系统权限目录真值，
	// 当前用户的权限快照统一收敛到 /auth/me。
	if _, err := requireAnyPermission(ctx, "roles:read", "permissions:read"); err != nil {
		return nil, err
	}
	catalog, err := h.permissionCatalog.Execute(ctx)
	if err != nil {
		return nil, err
	}
	return &openapi.SystemPermissionsResponse{
		Permissions: authorizationdomain.CanonicalPermissions(catalog.SystemPermissions),
	}, nil
}

func (h *Handlers) GetResourcePermissionCatalog(ctx context.Context) (*openapi.ResourcePermissionCatalogResponse, error) {
	if h == nil || h.permissionCatalog == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	// 关键设计：/permissions/resource 只暴露“资源权限目录 + 内建资源角色定义”，
	// 当前主体的资源快照统一收敛到 /auth/resource-permissions。
	if _, err := requireAnyPermission(ctx, "roles:read", "permissions:read"); err != nil {
		return nil, err
	}
	catalog, err := h.permissionCatalog.Execute(ctx)
	if err != nil {
		return nil, err
	}

	roles := make([]openapi.ResourceRoleDefinition, 0, len(catalog.ResourceRoles))
	for _, item := range catalog.ResourceRoles {
		roles = append(roles, mapResourceRoleDefinition(item))
	}
	return &openapi.ResourcePermissionCatalogResponse{
		Permissions: authorizationdomain.CanonicalPermissions(catalog.ResourcePermissions),
		Roles:       roles,
	}, nil
}

func (h *Handlers) ListUserSystemRoles(ctx context.Context, params openapi.ListUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	return h.listUserSystemRoles(ctx, params.PrincipalID)
}

func (h *Handlers) ReplaceUserSystemRoles(ctx context.Context, req *openapi.ReplaceUserSystemRolesRequest, params openapi.ReplaceUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	if h == nil || h.replaceUserRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	claims, err := requireRoleReplacementPermission(ctx)
	if err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(params.PrincipalID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidRoleInput
	}
	if claims.PrincipalID == principalID {
		return nil, accessapp.ErrForbidden
	}
	result, err := h.replaceUserRoles.Execute(ctx, authorizationapp.ReplaceUserSystemRolesCommand{
		PrincipalID: principalID,
		RoleIDs:     req.GetRoleIds(),
	})
	if err != nil {
		return nil, err
	}
	return mapUserSystemRoleBindings(result), nil
}

func (h *Handlers) listUserSystemRoles(ctx context.Context, rawPrincipalID string) ([]openapi.UserSystemRoleBinding, error) {
	if h == nil || h.userSystemRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	// 关键设计：查看用户系统角色既可以视为“读用户”，也可以视为“读角色”，
	// 因此这里只接受 canonical permission。
	if _, err := requireAnyPermission(ctx, "roles:read", "users:read"); err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(rawPrincipalID)
	if err != nil {
		return nil, accessapp.ErrForbidden
	}

	result, err := h.userSystemRoles.Execute(ctx, principalID)
	if err != nil {
		return nil, err
	}
	return mapUserSystemRoleBindings(result), nil
}
