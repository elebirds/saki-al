package repo

import (
	"context"
	"errors"
	"slices"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type MembershipAdminStore struct {
	q  *sqlcdb.Queries
	tx *appdb.TxRunner
}

var _ authorizationapp.ResourceMembershipStore = (*MembershipAdminStore)(nil)

func NewMembershipAdminStore(pool *pgxpool.Pool) *MembershipAdminStore {
	return &MembershipAdminStore{
		q:  sqlcdb.New(pool),
		tx: appdb.NewTxRunner(pool),
	}
}

func (r *MembershipAdminStore) ListResourceMembers(ctx context.Context, ref authorizationdomain.ResourceRef) ([]authorizationapp.ResourceMemberView, error) {
	if err := ensureResourceExists(ctx, r.q, ref); err != nil {
		return nil, err
	}

	rows, err := r.q.ListAuthzResourceMemberships(ctx, sqlcdb.ListAuthzResourceMembershipsParams{
		ResourceType: ref.Type,
		ResourceID:   ref.ID,
	})
	if err != nil {
		return nil, err
	}

	result := make([]authorizationapp.ResourceMemberView, 0, len(rows))
	for _, row := range rows {
		user, err := r.q.GetIamUserByPrincipalID(ctx, row.PrincipalID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				continue
			}
			return nil, err
		}
		role, err := r.q.GetAuthzRoleByID(ctx, row.RoleID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				continue
			}
			return nil, err
		}
		result = append(result, mapResourceMemberView(row, user, role))
	}
	return result, nil
}

func (r *MembershipAdminStore) UpsertResourceMember(ctx context.Context, principalID uuid.UUID, roleID uuid.UUID, ref authorizationdomain.ResourceRef) (*authorizationapp.ResourceMemberView, error) {
	var result *authorizationapp.ResourceMemberView
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		if err := ensureResourceExists(ctx, q, ref); err != nil {
			return err
		}
		if _, err := ensureActiveUser(ctx, q, principalID); err != nil {
			return err
		}
		if err := ensureBuiltinResourceRoles(ctx, q, ref.Type); err != nil {
			return err
		}

		role, err := q.GetAuthzRoleByID(ctx, roleID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return authorizationapp.ErrRoleNotFound
			}
			return err
		}
		if authorizationdomain.RoleScopeKind(role.ScopeKind) != authorizationdomain.RoleScopeResource {
			return authorizationapp.ErrInvalidRoleScope
		}
		// 关键设计：members 写路径只接受代码目录里声明为 assignable 的内建 resource role。
		// 这样可以彻底阻断“只要 scope_kind=resource 就能挂到任意资源”这类旧语义回潮。
		if !authorizationdomain.IsAssignableResourceRole(ref.Type, role.Name) {
			return authorizationapp.ErrResourceRoleNotAssignable
		}

		row, err := q.UpsertAuthzResourceMembership(ctx, sqlcdb.UpsertAuthzResourceMembershipParams{
			PrincipalID:  principalID,
			RoleID:       roleID,
			ResourceType: ref.Type,
			ResourceID:   ref.ID,
		})
		if err != nil {
			return err
		}

		user, err := q.GetIamUserByPrincipalID(ctx, row.PrincipalID)
		if err != nil {
			return err
		}
		storedRole, err := q.GetAuthzRoleByID(ctx, row.RoleID)
		if err != nil {
			return err
		}
		view := mapResourceMemberView(row, user, storedRole)
		result = &view
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *MembershipAdminStore) DeleteResourceMember(ctx context.Context, principalID uuid.UUID, ref authorizationdomain.ResourceRef) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		if err := ensureResourceExists(ctx, q, ref); err != nil {
			return err
		}

		rows, err := q.ListAuthzResourceMemberships(ctx, sqlcdb.ListAuthzResourceMembershipsParams{
			ResourceType: ref.Type,
			ResourceID:   ref.ID,
		})
		if err != nil {
			return err
		}

		var target *sqlcdb.AuthzResourceMembership
		for _, row := range rows {
			if row.PrincipalID == principalID {
				copy := row
				target = &copy
				break
			}
		}
		if target == nil {
			return authorizationapp.ErrResourceMembershipNotFound
		}

		role, err := q.GetAuthzRoleByID(ctx, target.RoleID)
		if err != nil {
			return err
		}
		if role.IsSupremo || authorizationdomain.IsOwnerResourceRole(ref.Type, role.Name) {
			return authorizationapp.ErrResourceOwnerImmutable
		}
		return q.DeleteAuthzResourceMembership(ctx, target.ID)
	})
}

func (r *MembershipAdminStore) ListAssignableResourceRoles(ctx context.Context, ref authorizationdomain.ResourceRef) ([]authorizationapp.ResourceRoleView, error) {
	result := make([]authorizationapp.ResourceRoleView, 0)
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)
		if err := ensureResourceExists(ctx, q, ref); err != nil {
			return err
		}
		if err := ensureBuiltinResourceRoles(ctx, q, ref.Type); err != nil {
			return err
		}

		definitions := authorizationdomain.AssignableResourceRoleDefinitions(ref.Type)
		result = make([]authorizationapp.ResourceRoleView, 0, len(definitions))
		for _, definition := range definitions {
			role, err := q.GetAuthzRoleByName(ctx, definition.Name)
			if err != nil {
				return err
			}
			result = append(result, mapResourceRoleView(role))
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *MembershipAdminStore) GetResourceRole(ctx context.Context, principalID uuid.UUID, ref authorizationdomain.ResourceRef) (*authorizationapp.ResourceRoleView, error) {
	if err := ensureResourceExists(ctx, r.q, ref); err != nil {
		return nil, err
	}

	rows, err := r.q.ListAuthzMembershipsByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		if row.ResourceType != ref.Type || row.ResourceID != ref.ID {
			continue
		}
		role, err := r.q.GetAuthzRoleByID(ctx, row.RoleID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return nil, nil
			}
			return nil, err
		}
		view := mapResourceRoleView(role)
		return &view, nil
	}
	return nil, nil
}

func ensureBuiltinResourceRoles(ctx context.Context, q *sqlcdb.Queries, resourceType string) error {
	definitions := authorizationdomain.ResourceRoleDefinitions(resourceType)
	for _, definition := range definitions {
		// 关键设计：数据库里的 resource role 只是代码目录的镜像，不是自由运营配置。
		// 每次成员相关 API 进入写路径前都做一次 reconcile，确保稳定 ID 存在，同时把权限集合拉回代码真值。
		role, err := q.GetAuthzRoleByName(ctx, definition.Name)
		switch {
		case err == nil:
		case errors.Is(err, pgx.ErrNoRows):
			role, err = q.CreateAuthzRole(ctx, sqlcdb.CreateAuthzRoleParams{
				ScopeKind:   string(authorizationdomain.RoleScopeResource),
				Name:        definition.Name,
				DisplayName: definition.DisplayName,
				Description: toRoleText(stringPtr(definition.Description)),
				BuiltIn:     true,
				Mutable:     false,
				Color:       definition.Color,
				IsSupremo:   definition.IsSupremo,
				SortOrder:   int32(definition.SortOrder),
			})
			if err != nil {
				return err
			}
		default:
			return err
		}

		role, err = q.UpdateAuthzRoleMetadata(ctx, sqlcdb.UpdateAuthzRoleMetadataParams{
			ID:          role.ID,
			ScopeKind:   string(authorizationdomain.RoleScopeResource),
			DisplayName: definition.DisplayName,
			Description: pgtype.Text{String: definition.Description, Valid: definition.Description != ""},
			BuiltIn:     true,
			Mutable:     false,
			Color:       definition.Color,
			IsSupremo:   definition.IsSupremo,
			SortOrder:   int32(definition.SortOrder),
		})
		if err != nil {
			return err
		}

		currentPermissions, err := q.ListAuthzRolePermissions(ctx, role.ID)
		if err != nil {
			return err
		}
		current := make(map[string]struct{}, len(currentPermissions))
		for _, permission := range currentPermissions {
			current[permission.Permission] = struct{}{}
		}
		for _, permission := range definition.Permissions {
			if _, ok := current[permission]; ok {
				continue
			}
			if err := q.AddAuthzRolePermission(ctx, sqlcdb.AddAuthzRolePermissionParams{
				RoleID:     role.ID,
				Permission: permission,
			}); err != nil {
				return err
			}
		}
		for permission := range current {
			if slices.Contains(definition.Permissions, permission) {
				continue
			}
			if err := q.RemoveAuthzRolePermission(ctx, sqlcdb.RemoveAuthzRolePermissionParams{
				RoleID:     role.ID,
				Permission: permission,
			}); err != nil {
				return err
			}
		}
	}
	return nil
}

func ensureActiveUser(ctx context.Context, q *sqlcdb.Queries, principalID uuid.UUID) (*sqlcdb.IamUser, error) {
	user, err := q.GetIamUserByPrincipalID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, identityapp.ErrUserNotFound
		}
		return nil, err
	}
	if identitydomain.UserState(user.State) == identitydomain.UserStateDeleted {
		return nil, identityapp.ErrUserNotFound
	}
	return &user, nil
}

func ensureResourceExists(ctx context.Context, q *sqlcdb.Queries, ref authorizationdomain.ResourceRef) error {
	switch ref.Type {
	case authorizationdomain.ResourceTypeProject:
		if _, err := q.GetProject(ctx, ref.ID); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return authorizationapp.ErrResourceNotFound
			}
			return err
		}
		return nil
	case authorizationdomain.ResourceTypeDataset:
		if _, err := q.GetDataset(ctx, ref.ID); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return authorizationapp.ErrResourceNotFound
			}
			return err
		}
		return nil
	default:
		return authorizationapp.ErrInvalidResourceType
	}
}

func mapResourceRoleView(role sqlcdb.AuthzRole) authorizationapp.ResourceRoleView {
	return authorizationapp.ResourceRoleView{
		ID:          role.ID.String(),
		Name:        role.Name,
		DisplayName: role.DisplayName,
		Description: role.Description.String,
		Color:       role.Color,
		IsSupremo:   role.IsSupremo,
	}
}

func mapResourceMemberView(membership sqlcdb.AuthzResourceMembership, user sqlcdb.IamUser, role sqlcdb.AuthzRole) authorizationapp.ResourceMemberView {
	return authorizationapp.ResourceMemberView{
		ID:              membership.ID.String(),
		ResourceType:    membership.ResourceType,
		ResourceID:      membership.ResourceID.String(),
		PrincipalID:     membership.PrincipalID.String(),
		RoleID:          membership.RoleID.String(),
		CreatedAt:       membership.CreatedAt.Time,
		UpdatedAt:       membership.UpdatedAt.Time,
		UserEmail:       user.Email,
		UserFullName:    user.FullName.String,
		RoleName:        role.Name,
		RoleDisplayName: role.DisplayName,
		RoleColor:       role.Color,
		RoleIsSupremo:   role.IsSupremo,
	}
}

func stringPtr(value string) *string {
	if value == "" {
		return nil
	}
	copy := value
	return &copy
}
