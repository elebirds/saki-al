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
	ScopeKind   authorizationdomain.RoleScopeKind
	Name        string
	DisplayName string
	Description string
	BuiltIn     bool
	Mutable     bool
	Color       string
	IsSupremo   bool
	SortOrder   int
}

type ListRolesParams struct {
	ScopeKind authorizationdomain.RoleScopeKind
	Offset    int
	Limit     int
}

type RolePage struct {
	Items  []authorizationdomain.Role
	Total  int
	Offset int
	Limit  int
}

type RoleRepo struct {
	q *sqlcdb.Queries
}

func NewRoleRepo(pool *pgxpool.Pool) *RoleRepo {
	return &RoleRepo{q: sqlcdb.New(pool)}
}

func (r *RoleRepo) Create(ctx context.Context, params CreateRoleParams) (*authorizationdomain.Role, error) {
	row, err := r.q.CreateAuthzRole(ctx, sqlcdb.CreateAuthzRoleParams{
		ScopeKind:   string(params.ScopeKind),
		Name:        params.Name,
		DisplayName: params.DisplayName,
		Description: pgtype.Text{String: params.Description, Valid: params.Description != ""},
		BuiltIn:     params.BuiltIn,
		Mutable:     params.Mutable,
		Color:       params.Color,
		IsSupremo:   params.IsSupremo,
		SortOrder:   int32(params.SortOrder),
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

func (r *RoleRepo) GetByID(ctx context.Context, id uuid.UUID) (*authorizationdomain.Role, error) {
	row, err := r.q.GetAuthzRoleByID(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapRole(row), nil
}

func (r *RoleRepo) CountByScope(ctx context.Context, scopeKind authorizationdomain.RoleScopeKind) (int, error) {
	total, err := r.q.CountAuthzRoles(ctx, string(scopeKind))
	if err != nil {
		return 0, err
	}
	return int(total), nil
}

func (r *RoleRepo) ListByScope(ctx context.Context, scopeKind authorizationdomain.RoleScopeKind, offset int, limit int) ([]authorizationdomain.Role, error) {
	rows, err := r.q.ListAuthzRoles(ctx, sqlcdb.ListAuthzRolesParams{
		ScopeKind:   string(scopeKind),
		OffsetCount: int32(offset),
		LimitCount:  int32(limit),
	})
	if err != nil {
		return nil, err
	}

	result := make([]authorizationdomain.Role, 0, len(rows))
	for _, row := range rows {
		result = append(result, *mapRole(row))
	}
	return result, nil
}

func (r *RoleRepo) List(ctx context.Context, params ListRolesParams) (*RolePage, error) {
	total, err := r.CountByScope(ctx, params.ScopeKind)
	if err != nil {
		return nil, err
	}
	rows, err := r.ListByScope(ctx, params.ScopeKind, params.Offset, params.Limit)
	if err != nil {
		return nil, err
	}
	return &RolePage{
		Items:  rows,
		Total:  total,
		Offset: params.Offset,
		Limit:  params.Limit,
	}, nil
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
		ScopeKind:   authorizationdomain.RoleScopeKind(row.ScopeKind),
		Name:        row.Name,
		DisplayName: row.DisplayName,
		Description: row.Description.String,
		BuiltIn:     row.BuiltIn,
		Mutable:     row.Mutable,
		Color:       row.Color,
		IsSupremo:   row.IsSupremo,
		SortOrder:   int(row.SortOrder),
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
