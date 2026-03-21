package apihttp

import (
	"context"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
)

// 鉴权会话流只处理登录、刷新、注册、改密等协议映射，不承载后台用户管理语义。
func (h *Handlers) Login(ctx context.Context, req *openapi.AuthLoginRequest) (*openapi.AuthSessionResponse, error) {
	identifier, ok := req.GetIdentifier().Get()
	if !ok || identifier == "" {
		return nil, accessapp.ErrUnauthorized
	}
	password, ok := req.GetPassword().Get()
	if !ok || password == "" {
		return nil, accessapp.ErrUnauthorized
	}

	session, err := h.login.Execute(ctx, identityapp.LoginCommand{
		Identifier: identifier,
		Password:   password,
	})
	if err != nil {
		return nil, err
	}
	return mapAuthSession(session), nil
}

func (h *Handlers) RefreshAuthSession(ctx context.Context, req *openapi.AuthRefreshRequest) (*openapi.AuthSessionResponse, error) {
	session, err := h.refresh.Execute(ctx, identityapp.RefreshCommand{
		RefreshToken: req.GetRefreshToken(),
	})
	if err != nil {
		return nil, err
	}
	return mapAuthSession(session), nil
}

func (h *Handlers) LogoutAuthSession(ctx context.Context, req *openapi.AuthLogoutRequest) error {
	return h.logout.Execute(ctx, identityapp.LogoutCommand{
		RefreshToken: req.GetRefreshToken(),
	})
}

func (h *Handlers) RegisterAuthUser(ctx context.Context, req *openapi.AuthRegisterRequest) (*openapi.AuthSessionResponse, error) {
	session, err := h.register.Execute(ctx, identityapp.RegisterCommand{
		Email:    req.GetEmail(),
		Password: req.GetPassword(),
		FullName: req.GetFullName(),
	})
	if err != nil {
		return nil, err
	}
	return mapAuthSession(session), nil
}

func (h *Handlers) ChangePassword(ctx context.Context, req *openapi.AuthChangePasswordRequest) (*openapi.AuthSessionResponse, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}

	session, err := h.changePassword.Execute(ctx, identityapp.ChangePasswordCommand{
		PrincipalID: claims.PrincipalID,
		OldPassword: req.GetOldPassword(),
		NewPassword: req.GetNewPassword(),
	})
	if err != nil {
		return nil, err
	}
	return mapAuthSession(session), nil
}
