package app

import (
	"context"
	"time"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
)

type UserRoleSummary struct {
	ID          string
	Name        string
	DisplayName string
	Color       string
	IsSupremo   bool
}

type UserAdminView struct {
	ID                 string
	Email              string
	FullName           string
	IsActive           bool
	MustChangePassword bool
	CreatedAt          time.Time
	UpdatedAt          time.Time
	Roles              []UserRoleSummary
}

type ListUsersInput struct {
	Page  int
	Limit int
}

type ListUsersResult struct {
	Items   []UserAdminView
	Total   int
	Offset  int
	Limit   int
	Size    int
	HasMore bool
}

type AdminUserStore interface {
	Count(ctx context.Context) (int, error)
	ListAdminRecords(ctx context.Context, offset int, limit int) ([]identitydomain.AdminUserRecord, error)
}

type AdminUserBindingStore interface {
	ListByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.SystemBinding, error)
}

type AdminRoleStore interface {
	GetByID(ctx context.Context, roleID uuid.UUID) (*authorizationdomain.Role, error)
}

type ListUsersUseCase struct {
	users    AdminUserStore
	bindings AdminUserBindingStore
	roles    AdminRoleStore
}

func NewListUsersUseCase(users AdminUserStore, bindings AdminUserBindingStore, roles AdminRoleStore) *ListUsersUseCase {
	return &ListUsersUseCase{
		users:    users,
		bindings: bindings,
		roles:    roles,
	}
}

func (u *ListUsersUseCase) Execute(ctx context.Context, input ListUsersInput) (*ListUsersResult, error) {
	_, limit, offset := normalizePage(input.Page, input.Limit)

	total, err := u.users.Count(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := u.users.ListAdminRecords(ctx, offset, limit)
	if err != nil {
		return nil, err
	}
	if rows == nil {
		return &ListUsersResult{
			Items:   nil,
			Total:   0,
			Offset:  offset,
			Limit:   limit,
			Size:    0,
			HasMore: false,
		}, nil
	}

	items := make([]UserAdminView, 0, len(rows))
	for _, row := range rows {
		roleBindings, err := u.bindings.ListByPrincipal(ctx, row.User.PrincipalID)
		if err != nil {
			return nil, err
		}

		roles := make([]UserRoleSummary, 0, len(roleBindings))
		for _, binding := range roleBindings {
			role, err := u.roles.GetByID(ctx, binding.RoleID)
			if err != nil {
				return nil, err
			}
			if role == nil {
				continue
			}
			roles = append(roles, UserRoleSummary{
				ID:          role.ID.String(),
				Name:        role.Name,
				DisplayName: role.DisplayName,
				Color:       role.Color,
				IsSupremo:   role.IsSupremo,
			})
		}

		items = append(items, UserAdminView{
			ID:                 row.User.PrincipalID.String(),
			Email:              row.User.Email,
			FullName:           derefString(row.User.FullName),
			IsActive:           isUserActive(row),
			MustChangePassword: row.MustChangePassword,
			CreatedAt:          row.User.CreatedAt,
			UpdatedAt:          row.User.UpdatedAt,
			Roles:              roles,
		})
	}

	return &ListUsersResult{
		Items:   items,
		Total:   total,
		Offset:  offset,
		Limit:   limit,
		Size:    len(items),
		HasMore: offset+len(items) < total,
	}, nil
}

func isUserActive(record identitydomain.AdminUserRecord) bool {
	return record.User.State != identitydomain.UserStateDisabled &&
		record.PrincipalStatus != identitydomain.PrincipalStatusDisabled
}

func derefString(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func normalizePage(page int, limit int) (int, int, int) {
	if page <= 0 {
		page = 1
	}
	if limit <= 0 {
		limit = 20
	}
	if limit > 200 {
		limit = 200
	}
	return page, limit, (page - 1) * limit
}
