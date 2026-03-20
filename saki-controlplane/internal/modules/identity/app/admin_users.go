package app

import (
	"context"
	"strings"
	"time"

	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

type AdminUserRecordStore interface {
	GetAdminUserRecord(ctx context.Context, principalID uuid.UUID) (*identitydomain.AdminUserRecord, error)
}

type AdminUserMutationStore interface {
	CreateAdminUser(ctx context.Context, params CreateAdminUserParams) (*identitydomain.AdminUserRecord, error)
	UpdateAdminUser(ctx context.Context, params UpdateAdminUserParams) (*identitydomain.AdminUserRecord, error)
	SoftDeleteAdminUser(ctx context.Context, params DeleteAdminUserParams) error
}

type CreateAdminUserParams struct {
	Email              string
	FullName           *string
	PasswordHash       string
	MustChangePassword bool
	IsActive           bool
	Now                time.Time
}

type UpdateAdminUserParams struct {
	PrincipalID        uuid.UUID
	FullName           *string
	ChangeFullName     bool
	PasswordHash       *string
	MustChangePassword bool
	IsActive           *bool
	Now                time.Time
}

type DeleteAdminUserParams struct {
	PrincipalID uuid.UUID
	Now         time.Time
}

type CreateUserCommand struct {
	Email    string
	Password string
	FullName *string
	IsActive bool
}

type UpdateUserCommand struct {
	UserID         uuid.UUID
	FullName       *string
	ChangeFullName bool
	IsActive       *bool
	Password       *string
}

type GetUserUseCase struct {
	store    AdminUserRecordStore
	bindings AdminUserBindingStore
	roles    AdminRoleStore
}

func NewGetUserUseCase(store AdminUserRecordStore, bindings AdminUserBindingStore, roles AdminRoleStore) *GetUserUseCase {
	return &GetUserUseCase{
		store:    store,
		bindings: bindings,
		roles:    roles,
	}
}

func (u *GetUserUseCase) Execute(ctx context.Context, principalID uuid.UUID) (*UserAdminView, error) {
	record, err := u.store.GetAdminUserRecord(ctx, principalID)
	if err != nil {
		return nil, err
	}
	if record == nil || record.User.State == identitydomain.UserStateDeleted {
		return nil, ErrUserNotFound
	}
	return buildUserAdminView(ctx, *record, u.bindings, u.roles)
}

type CreateUserUseCase struct {
	store     AdminUserMutationStore
	bindings  AdminUserBindingStore
	roles     AdminRoleStore
	passwords *PasswordHasher
	now       func() time.Time
}

func NewCreateUserUseCase(store AdminUserMutationStore, bindings AdminUserBindingStore, roles AdminRoleStore) *CreateUserUseCase {
	return &CreateUserUseCase{
		store:     store,
		bindings:  bindings,
		roles:     roles,
		passwords: NewPasswordHasher(),
		now:       time.Now,
	}
}

func (u *CreateUserUseCase) Execute(ctx context.Context, cmd CreateUserCommand) (*UserAdminView, error) {
	email := normalizeAdminEmail(cmd.Email)
	if email == "" || strings.TrimSpace(cmd.Password) == "" {
		return nil, ErrInvalidUserInput
	}

	passwordHash, err := u.passwords.Hash(cmd.Password)
	if err != nil {
		return nil, err
	}

	record, err := u.store.CreateAdminUser(ctx, CreateAdminUserParams{
		Email:              email,
		FullName:           normalizeOptionalName(cmd.FullName),
		PasswordHash:       passwordHash,
		MustChangePassword: true,
		IsActive:           cmd.IsActive,
		Now:                u.now().UTC(),
	})
	if err != nil {
		return nil, err
	}
	return buildUserAdminView(ctx, *record, u.bindings, u.roles)
}

type UpdateUserUseCase struct {
	store     AdminUserMutationStore
	bindings  AdminUserBindingStore
	roles     AdminRoleStore
	passwords *PasswordHasher
	now       func() time.Time
}

func NewUpdateUserUseCase(store AdminUserMutationStore, bindings AdminUserBindingStore, roles AdminRoleStore) *UpdateUserUseCase {
	return &UpdateUserUseCase{
		store:     store,
		bindings:  bindings,
		roles:     roles,
		passwords: NewPasswordHasher(),
		now:       time.Now,
	}
}

func (u *UpdateUserUseCase) Execute(ctx context.Context, cmd UpdateUserCommand) (*UserAdminView, error) {
	if cmd.UserID == uuid.Nil {
		return nil, ErrInvalidUserInput
	}
	params := UpdateAdminUserParams{
		PrincipalID:        cmd.UserID,
		FullName:           normalizeOptionalName(cmd.FullName),
		ChangeFullName:     cmd.ChangeFullName,
		MustChangePassword: cmd.Password != nil,
		IsActive:           cmd.IsActive,
		Now:                u.now().UTC(),
	}
	if cmd.Password != nil {
		if strings.TrimSpace(*cmd.Password) == "" {
			return nil, ErrInvalidUserInput
		}
		passwordHash, err := u.passwords.Hash(*cmd.Password)
		if err != nil {
			return nil, err
		}
		params.PasswordHash = &passwordHash
	}

	record, err := u.store.UpdateAdminUser(ctx, params)
	if err != nil {
		return nil, err
	}
	return buildUserAdminView(ctx, *record, u.bindings, u.roles)
}

type DeleteUserUseCase struct {
	store AdminUserMutationStore
	now   func() time.Time
}

func NewDeleteUserUseCase(store AdminUserMutationStore) *DeleteUserUseCase {
	return &DeleteUserUseCase{
		store: store,
		now:   time.Now,
	}
}

func (u *DeleteUserUseCase) Execute(ctx context.Context, principalID uuid.UUID) error {
	if principalID == uuid.Nil {
		return ErrInvalidUserInput
	}
	return u.store.SoftDeleteAdminUser(ctx, DeleteAdminUserParams{
		PrincipalID: principalID,
		Now:         u.now().UTC(),
	})
}

func buildUserAdminView(ctx context.Context, record identitydomain.AdminUserRecord, bindings AdminUserBindingStore, roles AdminRoleStore) (*UserAdminView, error) {
	roleBindings, err := bindings.ListByPrincipal(ctx, record.User.PrincipalID)
	if err != nil {
		return nil, err
	}

	roleViews := make([]UserRoleSummary, 0, len(roleBindings))
	for _, binding := range roleBindings {
		role, err := roles.GetByID(ctx, binding.RoleID)
		if err != nil {
			return nil, err
		}
		if role == nil {
			continue
		}
		roleViews = append(roleViews, UserRoleSummary{
			ID:          role.ID.String(),
			Name:        role.Name,
			DisplayName: role.DisplayName,
			Color:       role.Color,
			IsSupremo:   role.IsSupremo,
		})
	}

	return &UserAdminView{
		ID:                 record.User.PrincipalID.String(),
		Email:              record.User.Email,
		FullName:           derefString(record.User.FullName),
		IsActive:           isUserActive(record),
		MustChangePassword: record.MustChangePassword,
		CreatedAt:          record.User.CreatedAt,
		UpdatedAt:          record.User.UpdatedAt,
		Roles:              roleViews,
	}, nil
}

func normalizeAdminEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

func normalizeOptionalName(value *string) *string {
	if value == nil {
		return nil
	}
	trimmed := strings.TrimSpace(*value)
	if trimmed == "" {
		return nil
	}
	copy := trimmed
	return &copy
}
