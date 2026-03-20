package repo

import (
	"context"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type BindingRepo struct {
	q *sqlcdb.Queries
}

func NewBindingRepo(pool *pgxpool.Pool) *BindingRepo {
	return &BindingRepo{q: sqlcdb.New(pool)}
}

func (r *BindingRepo) ListByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.SystemBinding, error) {
	rows, err := r.q.ListAuthzSystemBindingsByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	result := make([]authorizationdomain.SystemBinding, 0, len(rows))
	for _, row := range rows {
		result = append(result, mapSystemBinding(row))
	}
	return result, nil
}

func (r *BindingRepo) Upsert(ctx context.Context, principalID uuid.UUID, roleID uuid.UUID, systemName string) (*authorizationdomain.SystemBinding, error) {
	row, err := r.q.UpsertAuthzSystemBinding(ctx, sqlcdb.UpsertAuthzSystemBindingParams{
		PrincipalID: principalID,
		RoleID:      roleID,
		SystemName:  systemName,
	})
	if err != nil {
		return nil, err
	}
	binding := mapSystemBinding(row)
	return &binding, nil
}

func (r *BindingRepo) Delete(ctx context.Context, id uuid.UUID) error {
	return r.q.DeleteAuthzSystemBinding(ctx, id)
}

func mapSystemBinding(row sqlcdb.AuthzSystemBinding) authorizationdomain.SystemBinding {
	return authorizationdomain.SystemBinding{
		ID:          row.ID,
		PrincipalID: row.PrincipalID,
		RoleID:      row.RoleID,
		SystemName:  row.SystemName,
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
