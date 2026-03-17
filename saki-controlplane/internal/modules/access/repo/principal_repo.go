package repo

import (
	"context"
	"errors"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Principal struct {
	ID          uuid.UUID
	SubjectType string
	SubjectKey  string
	DisplayName string
	Status      string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

type UpsertBootstrapPrincipalParams struct {
	SubjectType string
	SubjectKey  string
	DisplayName string
	Permissions []string
}

type PrincipalRepo struct {
	q    *sqlcdb.Queries
	tx   *appdb.TxRunner
}

func NewPrincipalRepo(pool *pgxpool.Pool) *PrincipalRepo {
	return &PrincipalRepo{
		q:    sqlcdb.New(pool),
		tx:   appdb.NewTxRunner(pool),
	}
}

func (r *PrincipalRepo) GetByID(ctx context.Context, principalID uuid.UUID) (*Principal, error) {
	row, err := r.q.GetAccessPrincipalByID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return mapPrincipal(row), nil
}

func (r *PrincipalRepo) GetBySubjectKey(ctx context.Context, subjectType string, subjectKey string) (*Principal, error) {
	row, err := r.q.GetAccessPrincipalBySubjectKey(ctx, sqlcdb.GetAccessPrincipalBySubjectKeyParams{
		SubjectType: subjectType,
		SubjectKey:  subjectKey,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return mapPrincipal(row), nil
}

func (r *PrincipalRepo) ListPermissions(ctx context.Context, principalID uuid.UUID) ([]string, error) {
	return r.q.ListAccessPermissions(ctx, principalID)
}

func (r *PrincipalRepo) UpsertBootstrapPrincipal(ctx context.Context, params UpsertBootstrapPrincipalParams) (*Principal, error) {
	var principal *Principal
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		row, err := q.UpsertAccessPrincipal(ctx, sqlcdb.UpsertAccessPrincipalParams{
			SubjectType: params.SubjectType,
			SubjectKey:  params.SubjectKey,
			DisplayName: params.DisplayName,
		})
		if err != nil {
			return err
		}

		if err := q.DeleteAccessPermissions(ctx, row.ID); err != nil {
			return err
		}
		for _, permission := range params.Permissions {
			if err := q.AddAccessPermission(ctx, sqlcdb.AddAccessPermissionParams{
				PrincipalID: row.ID,
				Permission:  permission,
			}); err != nil {
				return err
			}
		}

		principal = mapPrincipal(row)
		return nil
	})
	if err != nil {
		return nil, err
	}

	return principal, nil
}

func mapPrincipal(row sqlcdb.AccessPrincipal) *Principal {
	return &Principal{
		ID:          row.ID,
		SubjectType: row.SubjectType,
		SubjectKey:  row.SubjectKey,
		DisplayName: row.DisplayName,
		Status:      row.Status,
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
