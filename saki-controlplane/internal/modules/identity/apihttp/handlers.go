package apihttp

import (
	"context"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	"github.com/google/uuid"
)

type LoginExecutor interface {
	Execute(ctx context.Context, cmd identityapp.LoginCommand) (*identityapp.AuthSession, error)
}

type RefreshExecutor interface {
	Execute(ctx context.Context, cmd identityapp.RefreshCommand) (*identityapp.AuthSession, error)
}

type LogoutExecutor interface {
	Execute(ctx context.Context, cmd identityapp.LogoutCommand) error
}

type RegisterExecutor interface {
	Execute(ctx context.Context, cmd identityapp.RegisterCommand) (*identityapp.AuthSession, error)
}

type ChangePasswordExecutor interface {
	Execute(ctx context.Context, cmd identityapp.ChangePasswordCommand) (*identityapp.AuthSession, error)
}

type CurrentUserExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID, permissions []string) (*identityapp.CurrentUser, error)
}

type HandlersDeps struct {
	Login          LoginExecutor
	Refresh        RefreshExecutor
	Logout         LogoutExecutor
	Register       RegisterExecutor
	ChangePassword ChangePasswordExecutor
	CurrentUser    CurrentUserExecutor
}

type Handlers struct {
	login          LoginExecutor
	refresh        RefreshExecutor
	logout         LogoutExecutor
	register       RegisterExecutor
	changePassword ChangePasswordExecutor
	currentUser    CurrentUserExecutor
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		login:          deps.Login,
		refresh:        deps.Refresh,
		logout:         deps.Logout,
		register:       deps.Register,
		changePassword: deps.ChangePassword,
		currentUser:    deps.CurrentUser,
	}
}

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

func (h *Handlers) GetCurrentUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}

	currentUser, err := h.currentUser.Execute(ctx, claims.PrincipalID, claims.Permissions)
	if err != nil {
		return nil, err
	}
	response := &openapi.CurrentUserResponse{
		User: openapi.AuthSessionUser{
			PrincipalID: currentUser.User.PrincipalID.String(),
			Email:       currentUser.User.Email,
			FullName:    currentUser.User.FullName,
		},
		SystemRoles:        append([]string(nil), currentUser.SystemRoles...),
		Permissions:        append([]string(nil), currentUser.Permissions...),
		MustChangePassword: currentUser.MustChangePassword,
	}
	response.UserID.SetTo(currentUser.User.Email)
	return response, nil
}

func mapAuthSession(session *identityapp.AuthSession) *openapi.AuthSessionResponse {
	response := &openapi.AuthSessionResponse{
		AccessToken:        session.AccessToken,
		RefreshToken:       session.RefreshToken,
		ExpiresIn:          session.ExpiresIn,
		MustChangePassword: session.MustChangePassword,
		Permissions:        append([]string{}, session.Permissions...),
		User: openapi.AuthSessionUser{
			PrincipalID: session.User.PrincipalID.String(),
			Email:       session.User.Email,
			FullName:    session.User.FullName,
		},
	}
	// 关键设计：新 identity 响应保留 access_token 作为主语义，同时补 token/user_id 别名，
	// 这样迁移期旧前端和旧 smoke 不必立刻一起切换，但不会重新引入旧的免密登录语义。
	response.Token.SetTo(session.AccessToken)
	response.UserID.SetTo(session.User.Email)
	return response
}
