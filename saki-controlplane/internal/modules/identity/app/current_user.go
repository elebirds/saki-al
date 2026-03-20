package app

import (
	"context"
	"slices"

	"github.com/google/uuid"
)

type CurrentUser struct {
	User               SessionUser
	SystemRoles        []string
	Permissions        []string
	MustChangePassword bool
}

type CurrentUserStore interface {
	FindAccountByPrincipalID(ctx context.Context, principalID uuid.UUID) (*AuthAccount, error)
	ListSystemRoleNamesByPrincipal(ctx context.Context, principalID uuid.UUID) ([]string, error)
}

type CurrentUserUseCase struct {
	store CurrentUserStore
}

func NewCurrentUserUseCase(store CurrentUserStore) *CurrentUserUseCase {
	return &CurrentUserUseCase{store: store}
}

func (u *CurrentUserUseCase) Execute(ctx context.Context, principalID uuid.UUID, permissions []string) (*CurrentUser, error) {
	account, err := u.store.FindAccountByPrincipalID(ctx, principalID)
	if err != nil {
		return nil, err
	}
	if account == nil || account.IsDisabled() {
		return nil, ErrInvalidCredentials
	}

	roles, err := u.store.ListSystemRoleNamesByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	mustChangePassword := false
	if credential := account.ActivePasswordCredential(); credential != nil {
		mustChangePassword = credential.MustChangePassword
	}

	return &CurrentUser{
		User: SessionUser{
			PrincipalID: account.User.PrincipalID,
			Email:       account.User.Email,
			FullName:    account.DisplayFullName(),
		},
		SystemRoles:        append([]string(nil), roles...),
		Permissions:        slices.Clone(permissions),
		MustChangePassword: mustChangePassword,
	}, nil
}
