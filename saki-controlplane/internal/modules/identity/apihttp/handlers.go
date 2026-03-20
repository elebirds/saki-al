package apihttp

import (
	"context"
	"slices"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
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

type ListUsersExecutor interface {
	Execute(ctx context.Context, input identityapp.ListUsersInput) (*identityapp.ListUsersResult, error)
}

type CreateUserExecutor interface {
	Execute(ctx context.Context, cmd identityapp.CreateUserCommand) (*identityapp.UserAdminView, error)
}

type GetUserExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID) (*identityapp.UserAdminView, error)
}

type UpdateUserExecutor interface {
	Execute(ctx context.Context, cmd identityapp.UpdateUserCommand) (*identityapp.UserAdminView, error)
}

type DeleteUserExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID) error
}

type HandlersDeps struct {
	Login          LoginExecutor
	Refresh        RefreshExecutor
	Logout         LogoutExecutor
	Register       RegisterExecutor
	ChangePassword ChangePasswordExecutor
	CurrentUser    CurrentUserExecutor
	ListUsers      ListUsersExecutor
	CreateUser     CreateUserExecutor
	GetUser        GetUserExecutor
	UpdateUser     UpdateUserExecutor
	DeleteUser     DeleteUserExecutor
}

type Handlers struct {
	login          LoginExecutor
	refresh        RefreshExecutor
	logout         LogoutExecutor
	register       RegisterExecutor
	changePassword ChangePasswordExecutor
	currentUser    CurrentUserExecutor
	listUsers      ListUsersExecutor
	createUser     CreateUserExecutor
	getUser        GetUserExecutor
	updateUser     UpdateUserExecutor
	deleteUser     DeleteUserExecutor
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		login:          deps.Login,
		refresh:        deps.Refresh,
		logout:         deps.Logout,
		register:       deps.Register,
		changePassword: deps.ChangePassword,
		currentUser:    deps.CurrentUser,
		listUsers:      deps.ListUsers,
		createUser:     deps.CreateUser,
		getUser:        deps.GetUser,
		updateUser:     deps.UpdateUser,
		deleteUser:     deps.DeleteUser,
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
		Permissions:        authorizationdomain.ExpandedPermissionsForTransport(currentUser.Permissions),
		MustChangePassword: currentUser.MustChangePassword,
	}
	response.UserID.SetTo(currentUser.User.Email)
	return response, nil
}

func (h *Handlers) ListUsers(ctx context.Context, params openapi.ListUsersParams) (*openapi.UserListResponse, error) {
	if h == nil || h.listUsers == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "users:read", "user:read", "user:read:all"); err != nil {
		return nil, err
	}

	page, _ := params.Page.Get()
	limit, _ := params.Limit.Get()
	result, err := h.listUsers.Execute(ctx, identityapp.ListUsersInput{
		Page:  int(page),
		Limit: int(limit),
	})
	if err != nil {
		return nil, err
	}

	items := make([]openapi.UserListItem, 0, len(result.Items))
	for _, item := range result.Items {
		items = append(items, mapUser(item))
	}

	return &openapi.UserListResponse{
		Items:   items,
		Total:   int32(result.Total),
		Offset:  int32(result.Offset),
		Limit:   int32(result.Limit),
		Size:    int32(result.Size),
		HasMore: result.HasMore,
	}, nil
}

func (h *Handlers) CreateUser(ctx context.Context, req *openapi.UserCreateRequest) (*openapi.UserListItem, error) {
	if h == nil || h.createUser == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "users:write", "user:create:all", "user:manage:all"); err != nil {
		return nil, err
	}
	if req.GetEmail() == "" || req.GetPassword() == "" {
		return nil, identityapp.ErrInvalidUserInput
	}

	fullName, hasFullName := req.GetFullName().Get()
	isActive, hasIsActive := req.GetIsActive().Get()
	if !hasIsActive {
		isActive = true
	}

	item, err := h.createUser.Execute(ctx, identityapp.CreateUserCommand{
		Email:    req.GetEmail(),
		Password: req.GetPassword(),
		FullName: optStringPtr(fullName, hasFullName),
		IsActive: isActive,
	})
	if err != nil {
		return nil, err
	}
	response := mapUser(*item)
	return &response, nil
}

func (h *Handlers) GetUser(ctx context.Context, params openapi.GetUserParams) (*openapi.UserListItem, error) {
	if h == nil || h.getUser == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "users:read", "user:read:all"); err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(params.UserID)
	if err != nil {
		return nil, identityapp.ErrInvalidUserInput
	}
	item, err := h.getUser.Execute(ctx, principalID)
	if err != nil {
		return nil, err
	}
	response := mapUser(*item)
	return &response, nil
}

func (h *Handlers) UpdateUser(ctx context.Context, req *openapi.UserUpdateRequest, params openapi.UpdateUserParams) (*openapi.UserListItem, error) {
	if h == nil || h.updateUser == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "users:write", "user:update:all", "user:manage:all"); err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(params.UserID)
	if err != nil {
		return nil, identityapp.ErrInvalidUserInput
	}
	fullName, hasFullName := req.GetFullName().Get()
	isActive, hasIsActive := req.GetIsActive().Get()
	password, hasPassword := req.GetPassword().Get()

	item, err := h.updateUser.Execute(ctx, identityapp.UpdateUserCommand{
		UserID:         principalID,
		FullName:       optStringPtr(fullName, hasFullName),
		ChangeFullName: hasFullName,
		IsActive:       optBoolPtr(isActive, hasIsActive),
		Password:       optStringPtr(password, hasPassword),
	})
	if err != nil {
		return nil, err
	}
	response := mapUser(*item)
	return &response, nil
}

func (h *Handlers) DeleteUser(ctx context.Context, params openapi.DeleteUserParams) error {
	if h == nil || h.deleteUser == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "users:write", "user:delete:all", "user:manage:all"); err != nil {
		return err
	}

	principalID, err := uuid.Parse(params.UserID)
	if err != nil {
		return identityapp.ErrInvalidUserInput
	}
	return h.deleteUser.Execute(ctx, principalID)
}

func mapAuthSession(session *identityapp.AuthSession) *openapi.AuthSessionResponse {
	response := &openapi.AuthSessionResponse{
		AccessToken:        session.AccessToken,
		RefreshToken:       session.RefreshToken,
		ExpiresIn:          session.ExpiresIn,
		MustChangePassword: session.MustChangePassword,
		Permissions:        authorizationdomain.ExpandedPermissionsForTransport(session.Permissions),
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

func mapUser(item identityapp.UserAdminView) openapi.UserListItem {
	response := openapi.UserListItem{
		ID:                 item.ID,
		Email:              item.Email,
		IsActive:           item.IsActive,
		MustChangePassword: item.MustChangePassword,
		CreatedAt:          item.CreatedAt,
		UpdatedAt:          item.UpdatedAt,
		Roles:              make([]openapi.UserRoleInfo, 0, len(item.Roles)),
	}
	if item.FullName != "" {
		response.FullName.SetTo(item.FullName)
	}
	for _, role := range item.Roles {
		response.Roles = append(response.Roles, openapi.UserRoleInfo{
			ID:          role.ID,
			Name:        role.Name,
			DisplayName: role.DisplayName,
			Color:       role.Color,
			IsSupremo:   role.IsSupremo,
		})
	}
	return response
}

func optStringPtr(value string, ok bool) *string {
	if !ok {
		return nil
	}
	copy := value
	return &copy
}

func optBoolPtr(value bool, ok bool) *bool {
	if !ok {
		return nil
	}
	copy := value
	return &copy
}

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}
	for _, permission := range permissions {
		if slices.Contains(claims.Permissions, permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
}
