package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

// 身份相关 endpoint 只做协议代理；参数形态校验留在 transport 边界，业务规则下沉到 identity 模块。
func (s *Server) ChangePassword(ctx context.Context, req *openapi.AuthChangePasswordRequest) (*openapi.AuthSessionResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.ChangePassword(ctx, req)
}

func (s *Server) Login(ctx context.Context, req *openapi.AuthLoginRequest) (*openapi.AuthSessionResponse, error) {
	identifier, hasIdentifier := req.GetIdentifier().Get()
	password, hasPassword := req.GetPassword().Get()
	if !hasIdentifier || !hasPassword {
		return nil, newBadRequest("identifier and password are required")
	}
	if identifier == "" || password == "" {
		return nil, newBadRequest("identifier and password are required")
	}
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.Login(ctx, req)
}

func (s *Server) GetCurrentUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.GetCurrentUser(ctx)
}

func (s *Server) ListUsers(ctx context.Context, params openapi.ListUsersParams) (*openapi.UserListResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.ListUsers(ctx, params)
}

func (s *Server) CreateUser(ctx context.Context, req *openapi.UserCreateRequest) (*openapi.UserListItem, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.CreateUser(ctx, req)
}

func (s *Server) GetUser(ctx context.Context, params openapi.GetUserParams) (*openapi.UserListItem, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return nil, newBadRequest("invalid principal_id")
	}
	return s.identity.GetUser(ctx, params)
}

func (s *Server) UpdateUser(ctx context.Context, req *openapi.UserUpdateRequest, params openapi.UpdateUserParams) (*openapi.UserListItem, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return nil, newBadRequest("invalid principal_id")
	}
	return s.identity.UpdateUser(ctx, req, params)
}

func (s *Server) DeleteUser(ctx context.Context, params openapi.DeleteUserParams) error {
	if s.identity == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return newBadRequest("invalid principal_id")
	}
	return s.identity.DeleteUser(ctx, params)
}

func (s *Server) LogoutAuthSession(ctx context.Context, req *openapi.AuthLogoutRequest) error {
	if s.identity == nil {
		return ogenhttp.ErrNotImplemented
	}
	return s.identity.LogoutAuthSession(ctx, req)
}

func (s *Server) RefreshAuthSession(ctx context.Context, req *openapi.AuthRefreshRequest) (*openapi.AuthSessionResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.RefreshAuthSession(ctx, req)
}

func (s *Server) RegisterAuthUser(ctx context.Context, req *openapi.AuthRegisterRequest) (*openapi.AuthSessionResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.RegisterAuthUser(ctx, req)
}
