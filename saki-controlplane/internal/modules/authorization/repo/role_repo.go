package repo

import (
	"context"
	"errors"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type CreateRoleParams struct {
	Name        string
	DisplayName string
	Description string
}

type RoleRepo struct {
	q *sqlcdb.Queries
}

func NewRoleRepo(pool *pgxpool.Pool) *RoleRepo {
	return &RoleRepo{q: sqlcdb.New(pool)}
}

func (r *RoleRepo) Create(ctx context.Context, params CreateRoleParams) (*authorizationdomain.Role, error) {
	row, err := r.q.CreateAuthzRole(ctx, sqlcdb.CreateAuthzRoleParams{
		Name:        params.Name,
		DisplayName: params.DisplayName,
		Description: pgtype.Text{String: params.Description, Valid: params.Description != ""},
	})
	if err != nil {
		return nil, err
	}
	return mapRole(row), nil
}

func (r *RoleRepo) GetByName(ctx context.Context, name string) (*authorizationdomain.Role, error) {
	row, err := r.q.GetAuthzRoleByName(ctx, name)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapRole(row), nil
}

func (r *RoleRepo) List(ctx context.Context) ([]authorizationdomain.Role, error) {
	rows, err := r.q.ListAuthzRoles(ctx)
	if err != nil {
		return nil, err
	}

	result := make([]authorizationdomain.Role, 0, len(rows))
	for _, row := range rows {
		result = append(result, *mapRole(row))
	}
	return result, nil
}

func (r *RoleRepo) ListPermissions(ctx context.Context, roleID uuid.UUID) ([]string, error) {
	rows, err := r.q.ListAuthzRolePermissions(ctx, roleID)
	if err != nil {
		return nil, err
	}

	permissions := make([]string, 0, len(rows))
	for _, row := range rows {
		permissions = append(permissions, row.Permission)
	}
	return permissions, nil
}

func (r *RoleRepo) AddPermission(ctx context.Context, roleID uuid.UUID, permission string) error {
	return r.q.AddAuthzRolePermission(ctx, sqlcdb.AddAuthzRolePermissionParams{
		RoleID:     roleID,
		Permission: permission,
	})
}

func (r *RoleRepo) RemovePermission(ctx context.Context, roleID uuid.UUID, permission string) error {
	return r.q.RemoveAuthzRolePermission(ctx, sqlcdb.RemoveAuthzRolePermissionParams{
		RoleID:     roleID,
		Permission: permission,
	})
}

func mapRole(row sqlcdb.AuthzRole) *authorizationdomain.Role {
	return &authorizationdomain.Role{
		ID:          row.ID,
		Name:        row.Name,
		DisplayName: row.DisplayName,
		Description: row.Description.String,
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
