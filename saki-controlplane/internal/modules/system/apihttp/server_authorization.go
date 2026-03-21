package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

// 授权域的系统级接口：transport 层仅做参数与能力闸门，不做权限推导。
func (s *Server) CreateRole(ctx context.Context, req *openapi.RoleCreateRequest) (*openapi.RoleListItem, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.CreateRole(ctx, req)
}

func (s *Server) GetRole(ctx context.Context, params openapi.GetRoleParams) (*openapi.RoleListItem, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetRole(ctx, params)
}

func (s *Server) UpdateRole(ctx context.Context, req *openapi.RoleUpdateRequest, params openapi.UpdateRoleParams) (*openapi.RoleListItem, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.UpdateRole(ctx, req, params)
}

func (s *Server) DeleteRole(ctx context.Context, params openapi.DeleteRoleParams) error {
	if s.authorization == nil {
		return ogenhttp.ErrNotImplemented
	}
	return s.authorization.DeleteRole(ctx, params)
}

func (s *Server) GetSystemPermissions(ctx context.Context) (*openapi.SystemPermissionsResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetSystemPermissions(ctx)
}

func (s *Server) GetCurrentResourcePermissions(ctx context.Context, params openapi.GetCurrentResourcePermissionsParams) (*openapi.CurrentResourcePermissionsResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetCurrentResourcePermissions(ctx, params)
}

func (s *Server) GetResourcePermissionCatalog(ctx context.Context) (*openapi.ResourcePermissionCatalogResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetResourcePermissionCatalog(ctx)
}

func (s *Server) ListRoles(ctx context.Context, params openapi.ListRolesParams) (*openapi.RoleListResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.ListRoles(ctx, params)
}

func (s *Server) ListUserSystemRoles(ctx context.Context, params openapi.ListUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return nil, newBadRequest("invalid principal_id")
	}
	return s.authorization.ListUserSystemRoles(ctx, params)
}

func (s *Server) ReplaceUserSystemRoles(ctx context.Context, req *openapi.ReplaceUserSystemRolesRequest, params openapi.ReplaceUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return nil, newBadRequest("invalid principal_id")
	}
	return s.authorization.ReplaceUserSystemRoles(ctx, req, params)
}
