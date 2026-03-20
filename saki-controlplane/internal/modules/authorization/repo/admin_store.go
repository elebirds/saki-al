package repo

import (
	"context"
	"errors"
	"fmt"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const authzRoleNameUniqueConstraint = "authz_role_name_unique"

type AdminStore struct {
	q  *sqlcdb.Queries
	tx *appdb.TxRunner
}

func NewAdminStore(pool *pgxpool.Pool) *AdminStore {
	return &AdminStore{
		q:  sqlcdb.New(pool),
		tx: appdb.NewTxRunner(pool),
	}
}

var _ authorizationapp.RoleDetailStore = (*AdminStore)(nil)
var _ authorizationapp.RoleMutationStore = (*AdminStore)(nil)

func (r *AdminStore) GetRole(ctx context.Context, roleID uuid.UUID) (*authorizationapp.RoleView, error) {
	return r.loadRoleView(ctx, r.q, roleID)
}

func (r *AdminStore) CreateSystemRole(ctx context.Context, params authorizationapp.CreateSystemRoleParams) (*authorizationapp.RoleView, error) {
	var result *authorizationapp.RoleView
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		role, err := q.CreateAuthzRole(ctx, sqlcdb.CreateAuthzRoleParams{
			ScopeKind:   string(authorizationdomain.RoleScopeSystem),
			Name:        params.Name,
			DisplayName: params.DisplayName,
			Description: toRoleText(params.Description),
			BuiltIn:     false,
			Mutable:     true,
			Color:       params.Color,
			IsSupremo:   false,
			SortOrder:   1000,
		})
		if err != nil {
			if isRoleConstraintViolation(err, authzRoleNameUniqueConstraint) {
				return authorizationapp.ErrRoleAlreadyExists
			}
			return err
		}

		for _, permission := range params.Permissions {
			if err := q.AddAuthzRolePermission(ctx, sqlcdb.AddAuthzRolePermissionParams{
				RoleID:     role.ID,
				Permission: permission,
			}); err != nil {
				return err
			}
		}

		result, err = r.loadRoleView(ctx, q, role.ID)
		return err
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AdminStore) UpdateSystemRole(ctx context.Context, params authorizationapp.UpdateSystemRoleParams) (*authorizationapp.RoleView, error) {
	var result *authorizationapp.RoleView
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		role, err := q.GetAuthzRoleByID(ctx, params.RoleID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return authorizationapp.ErrRoleNotFound
			}
			return err
		}
		if authorizationdomain.RoleScopeKind(role.ScopeKind) != authorizationdomain.RoleScopeSystem {
			return authorizationapp.ErrInvalidRoleScope
		}
		if role.BuiltIn || !role.Mutable {
			return authorizationapp.ErrRoleImmutable
		}

		displayName := role.DisplayName
		if params.ChangeDisplayName && params.DisplayName != nil {
			displayName = *params.DisplayName
		}
		description := role.Description
		if params.ChangeDescription {
			description = toRoleText(params.Description)
		}
		color := role.Color
		if params.ChangeColor {
			if params.Color != nil {
				color = *params.Color
			} else {
				color = "blue"
			}
		}

		if _, err := q.UpdateAuthzRoleMetadata(ctx, sqlcdb.UpdateAuthzRoleMetadataParams{
			ID:          role.ID,
			ScopeKind:   role.ScopeKind,
			DisplayName: displayName,
			Description: description,
			BuiltIn:     role.BuiltIn,
			Mutable:     role.Mutable,
			Color:       color,
			IsSupremo:   role.IsSupremo,
			SortOrder:   role.SortOrder,
		}); err != nil {
			return err
		}

		if params.ChangePermissions {
			currentPermissions, err := q.ListAuthzRolePermissions(ctx, role.ID)
			if err != nil {
				return err
			}
			current := make(map[string]struct{}, len(currentPermissions))
			for _, permission := range currentPermissions {
				current[permission.Permission] = struct{}{}
			}
			next := make(map[string]struct{}, len(params.Permissions))
			for _, permission := range params.Permissions {
				next[permission] = struct{}{}
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
				if _, ok := next[permission]; ok {
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

		result, err = r.loadRoleView(ctx, q, role.ID)
		return err
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AdminStore) DeleteRole(ctx context.Context, roleID uuid.UUID) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		role, err := q.GetAuthzRoleByID(ctx, roleID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return authorizationapp.ErrRoleNotFound
			}
			return err
		}
		if authorizationdomain.RoleScopeKind(role.ScopeKind) != authorizationdomain.RoleScopeSystem {
			return authorizationapp.ErrInvalidRoleScope
		}
		if role.BuiltIn || !role.Mutable {
			return authorizationapp.ErrRoleImmutable
		}
		return q.DeleteAuthzRole(ctx, roleID)
	})
}

func (r *AdminStore) ReplaceUserSystemRoles(ctx context.Context, principalID uuid.UUID, roleIDs []uuid.UUID) ([]authorizationapp.UserSystemRoleBindingView, error) {
	var result []authorizationapp.UserSystemRoleBindingView
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		user, err := q.GetIamUserByPrincipalID(ctx, principalID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return identityapp.ErrUserNotFound
			}
			return err
		}
		if identitydomain.UserState(user.State) == identitydomain.UserStateDeleted {
			return identityapp.ErrUserNotFound
		}

		for _, roleID := range roleIDs {
			role, err := q.GetAuthzRoleByID(ctx, roleID)
			if err != nil {
				if errors.Is(err, pgx.ErrNoRows) {
					return authorizationapp.ErrRoleNotFound
				}
				return err
			}
			if authorizationdomain.RoleScopeKind(role.ScopeKind) != authorizationdomain.RoleScopeSystem {
				return authorizationapp.ErrInvalidRoleScope
			}
		}

		existingBindings, err := q.ListAuthzSystemBindingsByPrincipal(ctx, principalID)
		if err != nil {
			return err
		}
		for _, binding := range existingBindings {
			if err := q.DeleteAuthzSystemBinding(ctx, binding.ID); err != nil {
				return err
			}
		}

		// 关键设计：原始表把 system role 设计成“一个用户在一个 system_name 槽位上绑定一个角色”。
		// 新的覆盖式 API 不再暴露槽位概念，但为了不额外引入迁移，我们用稳定 slot 名把它折叠成一个有序角色集合。
		for idx, roleID := range roleIDs {
			if _, err := q.UpsertAuthzSystemBinding(ctx, sqlcdb.UpsertAuthzSystemBindingParams{
				PrincipalID: principalID,
				RoleID:      roleID,
				SystemName:  fmt.Sprintf("slot-%03d", idx),
			}); err != nil {
				return err
			}
		}

		rows, err := q.ListAuthzSystemRoleBindingsByPrincipal(ctx, principalID)
		if err != nil {
			return err
		}
		result = make([]authorizationapp.UserSystemRoleBindingView, 0, len(rows))
		for _, row := range rows {
			result = append(result, authorizationapp.UserSystemRoleBindingView{
				ID:              row.ID.String(),
				UserID:          row.PrincipalID.String(),
				RoleID:          row.RoleID.String(),
				RoleName:        row.RoleName,
				RoleDisplayName: row.RoleDisplayName,
				RoleColor:       row.RoleColor,
				RoleIsSupremo:   row.RoleIsSupremo,
				AssignedAt:      row.CreatedAt.Time,
			})
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (r *AdminStore) loadRoleView(ctx context.Context, q *sqlcdb.Queries, roleID uuid.UUID) (*authorizationapp.RoleView, error) {
	role, err := q.GetAuthzRoleByID(ctx, roleID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	permissions, err := q.ListAuthzRolePermissions(ctx, roleID)
	if err != nil {
		return nil, err
	}

	view := &authorizationapp.RoleView{
		ID:          role.ID.String(),
		Name:        role.Name,
		DisplayName: role.DisplayName,
		Description: role.Description.String,
		Type:        role.ScopeKind,
		BuiltIn:     role.BuiltIn,
		Mutable:     role.Mutable,
		Color:       role.Color,
		IsSupremo:   role.IsSupremo,
		SortOrder:   int(role.SortOrder),
		IsSystem:    authorizationdomain.RoleScopeKind(role.ScopeKind) == authorizationdomain.RoleScopeSystem,
		Permissions: make([]authorizationapp.RolePermissionView, 0, len(permissions)),
		CreatedAt:   role.CreatedAt.Time,
		UpdatedAt:   role.UpdatedAt.Time,
	}
	for _, permission := range permissions {
		view.Permissions = append(view.Permissions, authorizationapp.RolePermissionView{
			Permission: permission.Permission,
		})
	}
	return view, nil
}

func toRoleText(value *string) pgtype.Text {
	if value == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *value, Valid: true}
}

func isRoleConstraintViolation(err error, constraintName string) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) &&
		pgErr.Code == "23505" &&
		pgErr.ConstraintName == constraintName
}
