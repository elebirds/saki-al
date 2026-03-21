package app

import (
	"context"
	"slices"
	"strings"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

type RoleDetailStore interface {
	GetRole(ctx context.Context, roleID uuid.UUID) (*RoleView, error)
}

type RoleMutationStore interface {
	CreateSystemRole(ctx context.Context, params CreateSystemRoleParams) (*RoleView, error)
	UpdateSystemRole(ctx context.Context, params UpdateSystemRoleParams) (*RoleView, error)
	DeleteRole(ctx context.Context, roleID uuid.UUID) error
	ReplaceUserSystemRoles(ctx context.Context, principalID uuid.UUID, roleIDs []uuid.UUID) ([]UserSystemRoleBindingView, error)
}

type CreateSystemRoleParams struct {
	Name        string
	DisplayName string
	Description *string
	Color       string
	Permissions []string
}

type UpdateSystemRoleParams struct {
	RoleID            uuid.UUID
	DisplayName       *string
	ChangeDisplayName bool
	Description       *string
	ChangeDescription bool
	Color             *string
	ChangeColor       bool
	Permissions       []string
	ChangePermissions bool
}

type CreateRoleCommand struct {
	Name        string
	DisplayName string
	Description *string
	Color       *string
	Permissions []string
}

type UpdateRoleCommand struct {
	RoleID            uuid.UUID
	DisplayName       *string
	ChangeDisplayName bool
	Description       *string
	ChangeDescription bool
	Color             *string
	ChangeColor       bool
	Permissions       []string
	ChangePermissions bool
}

type ReplaceUserSystemRolesCommand struct {
	PrincipalID uuid.UUID
	RoleIDs     []uuid.UUID
}

type GetRoleUseCase struct {
	store RoleDetailStore
}

func NewGetRoleUseCase(store RoleDetailStore) *GetRoleUseCase {
	return &GetRoleUseCase{store: store}
}

func (u *GetRoleUseCase) Execute(ctx context.Context, roleID uuid.UUID) (*RoleView, error) {
	if roleID == uuid.Nil {
		return nil, ErrInvalidRoleInput
	}
	role, err := u.store.GetRole(ctx, roleID)
	if err != nil {
		return nil, err
	}
	if role == nil {
		return nil, ErrRoleNotFound
	}
	return role, nil
}

type CreateRoleUseCase struct {
	store RoleMutationStore
}

func NewCreateRoleUseCase(store RoleMutationStore) *CreateRoleUseCase {
	return &CreateRoleUseCase{store: store}
}

func (u *CreateRoleUseCase) Execute(ctx context.Context, cmd CreateRoleCommand) (*RoleView, error) {
	if strings.TrimSpace(cmd.Name) == "" || strings.TrimSpace(cmd.DisplayName) == "" {
		return nil, ErrInvalidRoleInput
	}
	permissions, err := normalizePermissionsForScope(authorizationdomain.RoleScopeSystem, cmd.Permissions)
	if err != nil {
		return nil, err
	}

	return u.store.CreateSystemRole(ctx, CreateSystemRoleParams{
		Name:        strings.TrimSpace(cmd.Name),
		DisplayName: strings.TrimSpace(cmd.DisplayName),
		Description: normalizeOptionalText(cmd.Description),
		Color:       normalizeRoleColor(cmd.Color),
		Permissions: permissions,
	})
}

type UpdateRoleUseCase struct {
	store RoleMutationStore
}

func NewUpdateRoleUseCase(store RoleMutationStore) *UpdateRoleUseCase {
	return &UpdateRoleUseCase{store: store}
}

func (u *UpdateRoleUseCase) Execute(ctx context.Context, cmd UpdateRoleCommand) (*RoleView, error) {
	if cmd.RoleID == uuid.Nil {
		return nil, ErrInvalidRoleInput
	}
	if cmd.ChangeDisplayName && normalizeOptionalText(cmd.DisplayName) == nil {
		return nil, ErrInvalidRoleInput
	}
	params := UpdateSystemRoleParams{
		RoleID:            cmd.RoleID,
		DisplayName:       normalizeOptionalText(cmd.DisplayName),
		ChangeDisplayName: cmd.ChangeDisplayName,
		Description:       normalizeOptionalText(cmd.Description),
		ChangeDescription: cmd.ChangeDescription,
		Color:             normalizeOptionalColor(cmd.Color),
		ChangeColor:       cmd.ChangeColor,
		ChangePermissions: cmd.ChangePermissions,
	}
	if cmd.ChangePermissions {
		permissions, err := normalizePermissionsForScope(authorizationdomain.RoleScopeSystem, cmd.Permissions)
		if err != nil {
			return nil, err
		}
		params.Permissions = permissions
	}
	return u.store.UpdateSystemRole(ctx, params)
}

type DeleteRoleUseCase struct {
	store RoleMutationStore
}

func NewDeleteRoleUseCase(store RoleMutationStore) *DeleteRoleUseCase {
	return &DeleteRoleUseCase{store: store}
}

func (u *DeleteRoleUseCase) Execute(ctx context.Context, roleID uuid.UUID) error {
	if roleID == uuid.Nil {
		return ErrInvalidRoleInput
	}
	return u.store.DeleteRole(ctx, roleID)
}

type ReplaceUserSystemRolesUseCase struct {
	store RoleMutationStore
}

func NewReplaceUserSystemRolesUseCase(store RoleMutationStore) *ReplaceUserSystemRolesUseCase {
	return &ReplaceUserSystemRolesUseCase{store: store}
}

func (u *ReplaceUserSystemRolesUseCase) Execute(ctx context.Context, cmd ReplaceUserSystemRolesCommand) ([]UserSystemRoleBindingView, error) {
	if cmd.PrincipalID == uuid.Nil {
		return nil, ErrInvalidRoleInput
	}
	roleIDs := dedupeRoleIDs(cmd.RoleIDs)
	return u.store.ReplaceUserSystemRoles(ctx, cmd.PrincipalID, roleIDs)
}

func normalizePermissionsForScope(scope authorizationdomain.RoleScopeKind, permissions []string) ([]string, error) {
	allowed := authorizationdomain.PermissionsForRoleScope(scope)
	normalized := make([]string, 0, len(permissions))
	seen := make(map[string]struct{}, len(permissions))
	for _, permission := range permissions {
		canonical := authorizationdomain.CanonicalPermission(strings.TrimSpace(permission))
		if canonical == "" || !slices.Contains(allowed, canonical) {
			return nil, ErrInvalidRolePermission
		}
		if _, ok := seen[canonical]; ok {
			continue
		}
		seen[canonical] = struct{}{}
		normalized = append(normalized, canonical)
	}
	slices.Sort(normalized)
	return normalized, nil
}

func normalizeOptionalText(value *string) *string {
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

func normalizeRoleColor(value *string) string {
	normalized := normalizeOptionalColor(value)
	if normalized == nil {
		return "blue"
	}
	return *normalized
}

func normalizeOptionalColor(value *string) *string {
	if value == nil {
		return nil
	}
	trimmed := strings.TrimSpace(*value)
	if trimmed == "" {
		trimmed = "blue"
	}
	copy := trimmed
	return &copy
}

func dedupeRoleIDs(roleIDs []uuid.UUID) []uuid.UUID {
	result := make([]uuid.UUID, 0, len(roleIDs))
	seen := make(map[uuid.UUID]struct{}, len(roleIDs))
	for _, roleID := range roleIDs {
		if _, ok := seen[roleID]; ok {
			continue
		}
		seen[roleID] = struct{}{}
		result = append(result, roleID)
	}
	return result
}
