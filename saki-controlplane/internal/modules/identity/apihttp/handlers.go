package apihttp

import (
	"context"

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

// 关键设计：identity transport 入口只保留依赖装配。
// 鉴权会话流与用户管理流拆到独立 handler 文件，避免单个 handlers.go 同时承担两类协议职责。
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
