package repo

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type Sample struct {
	ID          uuid.UUID
	ProjectID   uuid.UUID
	DatasetType string
	Meta        []byte
	CreatedAt   time.Time
}

type CreateSampleParams struct {
	ProjectID   uuid.UUID
	DatasetType string
	Meta        []byte
}

type SampleRepo struct {
	q *sqlcdb.Queries
}

func NewSampleRepo(pool *pgxpool.Pool) *SampleRepo {
	return &SampleRepo{q: sqlcdb.New(pool)}
}

func (r *SampleRepo) Create(ctx context.Context, params CreateSampleParams) (*Sample, error) {
	row, err := r.q.CreateSample(ctx, sqlcdb.CreateSampleParams{
		ProjectID:   params.ProjectID,
		DatasetType: params.DatasetType,
		Meta:        params.Meta,
	})
	if err != nil {
		return nil, err
	}

	return &Sample{
		ID:          row.ID,
		ProjectID:   row.ProjectID,
		DatasetType: row.DatasetType,
		Meta:        row.Meta,
		CreatedAt:   row.CreatedAt.Time,
	}, nil
}

func (r *SampleRepo) Get(ctx context.Context, sampleID uuid.UUID) (*Sample, error) {
	row, err := r.q.GetSample(ctx, sampleID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return &Sample{
		ID:          row.ID,
		ProjectID:   row.ProjectID,
		DatasetType: row.DatasetType,
		Meta:        row.Meta,
		CreatedAt:   row.CreatedAt.Time,
	}, nil
}
