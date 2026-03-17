package repo

import (
	"context"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type SampleMatchRef struct {
	ID        int64
	DatasetID uuid.UUID
	SampleID  uuid.UUID
	RefType   string
	RefValue  string
	IsPrimary bool
	CreatedAt time.Time
}

type PutSampleMatchRefParams struct {
	DatasetID uuid.UUID
	SampleID  uuid.UUID
	RefType   string
	RefValue  string
	IsPrimary bool
}

type SampleMatchRefRepo struct {
	q *sqlcdb.Queries
}

func NewSampleMatchRefRepo(pool *pgxpool.Pool) *SampleMatchRefRepo {
	return &SampleMatchRefRepo{q: sqlcdb.New(pool)}
}

func (r *SampleMatchRefRepo) Put(ctx context.Context, params PutSampleMatchRefParams) (*SampleMatchRef, error) {
	row, err := r.q.PutSampleMatchRef(ctx, sqlcdb.PutSampleMatchRefParams{
		DatasetID: params.DatasetID,
		SampleID:  params.SampleID,
		RefType:   params.RefType,
		RefValue:  params.RefValue,
		IsPrimary: params.IsPrimary,
	})
	if err != nil {
		return nil, err
	}
	return &SampleMatchRef{
		ID:        row.ID,
		DatasetID: row.DatasetID,
		SampleID:  row.SampleID,
		RefType:   row.RefType,
		RefValue:  row.RefValue,
		IsPrimary: row.IsPrimary,
		CreatedAt: row.CreatedAt.Time,
	}, nil
}

func (r *SampleMatchRefRepo) FindExact(ctx context.Context, datasetID uuid.UUID, refType, refValue string) ([]SampleMatchRef, error) {
	rows, err := r.q.FindExactSampleMatchRefs(ctx, sqlcdb.FindExactSampleMatchRefsParams{
		DatasetID: datasetID,
		RefType:   refType,
		RefValue:  refValue,
	})
	if err != nil {
		return nil, err
	}
	refs := make([]SampleMatchRef, 0, len(rows))
	for _, row := range rows {
		refs = append(refs, SampleMatchRef{
			ID:        row.ID,
			DatasetID: row.DatasetID,
			SampleID:  row.SampleID,
			RefType:   row.RefType,
			RefValue:  row.RefValue,
			IsPrimary: row.IsPrimary,
			CreatedAt: row.CreatedAt.Time,
		})
	}
	return refs, nil
}
