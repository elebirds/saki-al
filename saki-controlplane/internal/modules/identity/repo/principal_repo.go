package repo

import (
	"context"
	"errors"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type PrincipalRepo struct {
	q *sqlcdb.Queries
}

func NewPrincipalRepo(pool *pgxpool.Pool) *PrincipalRepo {
	return &PrincipalRepo{q: sqlcdb.New(pool)}
}

func (r *PrincipalRepo) Create(ctx context.Context, kind identitydomain.PrincipalKind, displayName string) (*identitydomain.Principal, error) {
	row, err := r.q.CreateIamPrincipal(ctx, sqlcdb.CreateIamPrincipalParams{
		Kind:        sqlcdb.IamPrincipalKind(kind),
		DisplayName: displayName,
	})
	if err != nil {
		return nil, err
	}
	return mapPrincipal(row), nil
}

func (r *PrincipalRepo) GetByID(ctx context.Context, id uuid.UUID) (*identitydomain.Principal, error) {
	row, err := r.q.GetIamPrincipalByID(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapPrincipal(row), nil
}

func (r *PrincipalRepo) ListByKind(ctx context.Context, kind identitydomain.PrincipalKind) ([]identitydomain.Principal, error) {
	rows, err := r.q.ListIamPrincipalsByKind(ctx, sqlcdb.IamPrincipalKind(kind))
	if err != nil {
		return nil, err
	}

	result := make([]identitydomain.Principal, 0, len(rows))
	for _, row := range rows {
		result = append(result, *mapPrincipal(row))
	}
	return result, nil
}

func (r *PrincipalRepo) UpdateStatus(ctx context.Context, id uuid.UUID, status identitydomain.PrincipalStatus) error {
	return r.q.UpdateIamPrincipalStatus(ctx, sqlcdb.UpdateIamPrincipalStatusParams{
		ID:     id,
		Status: sqlcdb.IamPrincipalStatus(status),
	})
}

func mapPrincipal(row sqlcdb.IamPrincipal) *identitydomain.Principal {
	return &identitydomain.Principal{
		ID:          row.ID,
		Kind:        identitydomain.PrincipalKind(row.Kind),
		DisplayName: row.DisplayName,
		Status:      identitydomain.PrincipalStatus(row.Status),
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
