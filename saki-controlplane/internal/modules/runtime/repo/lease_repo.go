package repo

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type RuntimeLease struct {
	Name       string
	Holder     string
	Epoch      int64
	LeaseUntil time.Time
}

type AcquireLeaseParams struct {
	Name       string
	Holder     string
	LeaseUntil time.Time
}

type LeaseRepo struct {
	q *sqlcdb.Queries
}

func NewLeaseRepo(pool *pgxpool.Pool) *LeaseRepo {
	return &LeaseRepo{q: sqlcdb.New(pool)}
}

func (r *LeaseRepo) AcquireOrRenew(ctx context.Context, params AcquireLeaseParams) (*RuntimeLease, error) {
	row, err := r.q.CreateRuntimeLease(ctx, sqlcdb.CreateRuntimeLeaseParams{
		Name:       params.Name,
		Holder:     params.Holder,
		LeaseUntil: pgtype.Timestamptz{Time: params.LeaseUntil, Valid: true},
	})
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	if err == nil {
		return &RuntimeLease{
			Name:       row.Name,
			Holder:     row.Holder,
			Epoch:      row.Epoch,
			LeaseUntil: row.LeaseUntil.Time,
		}, nil
	}

	row, err = r.q.RenewRuntimeLease(ctx, sqlcdb.RenewRuntimeLeaseParams{
		Name:       params.Name,
		Holder:     params.Holder,
		LeaseUntil: pgtype.Timestamptz{Time: params.LeaseUntil, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	return &RuntimeLease{
		Name:       row.Name,
		Holder:     row.Holder,
		Epoch:      row.Epoch,
		LeaseUntil: row.LeaseUntil.Time,
	}, nil
}
