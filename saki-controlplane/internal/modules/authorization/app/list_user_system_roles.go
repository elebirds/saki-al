package app

import (
	"context"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

type UserSystemRoleBindingStore interface {
	ListByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.SystemBinding, error)
}

type UserSystemRoleStore interface {
	GetByID(ctx context.Context, roleID uuid.UUID) (*authorizationdomain.Role, error)
}

type ListUserSystemRolesUseCase struct {
	bindings UserSystemRoleBindingStore
	roles    UserSystemRoleStore
}

func NewListUserSystemRolesUseCase(bindings UserSystemRoleBindingStore, roles UserSystemRoleStore) *ListUserSystemRolesUseCase {
	return &ListUserSystemRolesUseCase{
		bindings: bindings,
		roles:    roles,
	}
}

func (u *ListUserSystemRolesUseCase) Execute(ctx context.Context, principalID uuid.UUID) ([]UserSystemRoleBindingView, error) {
	rows, err := u.bindings.ListByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	// 关键设计：用户详情页与系统角色编辑器都把“角色绑定”视为一个显式集合，
	// 所以这里直接返回绑定记录，而不是只返回 role name 字符串，后续覆盖式更新也能沿用同一模型。
	result := make([]UserSystemRoleBindingView, 0, len(rows))
	for _, row := range rows {
		role, err := u.roles.GetByID(ctx, row.RoleID)
		if err != nil {
			return nil, err
		}
		if role == nil {
			continue
		}
		result = append(result, UserSystemRoleBindingView{
			ID:              row.ID.String(),
			UserID:          row.PrincipalID.String(),
			RoleID:          row.RoleID.String(),
			RoleName:        role.Name,
			RoleDisplayName: role.DisplayName,
			RoleColor:       role.Color,
			RoleIsSupremo:   role.IsSupremo,
			AssignedAt:      row.CreatedAt,
		})
	}
	return result, nil
}
