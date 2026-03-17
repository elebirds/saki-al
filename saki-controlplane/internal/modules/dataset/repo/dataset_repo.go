package repo

import (
	"context"
	"errors"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Dataset struct {
	ID        uuid.UUID
	Name      string
	Type      string
	CreatedAt time.Time
	UpdatedAt time.Time
}

type CreateDatasetParams struct {
	Name string
	Type string
}

type UpdateDatasetParams struct {
	ID   uuid.UUID
	Name string
	Type string
}

type ListDatasetsParams struct {
	Query  string
	Offset int
	Limit  int
}

type DatasetPage struct {
	Items  []Dataset
	Total  int
	Offset int
	Limit  int
}

type DatasetRepo struct {
	q *sqlcdb.Queries
}

func NewDatasetRepo(pool *pgxpool.Pool) *DatasetRepo {
	return &DatasetRepo{q: sqlcdb.New(pool)}
}

func (r *DatasetRepo) Create(ctx context.Context, params CreateDatasetParams) (*Dataset, error) {
	row, err := r.q.CreateDataset(ctx, sqlcdb.CreateDatasetParams{
		Name: params.Name,
		Type: params.Type,
	})
	if err != nil {
		return nil, err
	}

	return &Dataset{
		ID:        row.ID,
		Name:      row.Name,
		Type:      row.Type,
		CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
	}, nil
}

func (r *DatasetRepo) Get(ctx context.Context, id uuid.UUID) (*Dataset, error) {
	row, err := r.q.GetDataset(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return &Dataset{
		ID:        row.ID,
		Name:      row.Name,
		Type:      row.Type,
		CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
	}, nil
}

func (r *DatasetRepo) List(ctx context.Context, params ListDatasetsParams) (*DatasetPage, error) {
	total, err := r.q.CountDatasets(ctx, params.Query)
	if err != nil {
		return nil, err
	}

	rows, err := r.q.ListDatasets(ctx, sqlcdb.ListDatasetsParams{
		QueryText:   params.Query,
		OffsetCount: int32(params.Offset),
		LimitCount:  int32(params.Limit),
	})
	if err != nil {
		return nil, err
	}

	datasets := make([]Dataset, 0, len(rows))
	for _, row := range rows {
		datasets = append(datasets, Dataset{
			ID:        row.ID,
			Name:      row.Name,
			Type:      row.Type,
			CreatedAt: row.CreatedAt.Time,
			UpdatedAt: row.UpdatedAt.Time,
		})
	}

	return &DatasetPage{
		Items:  datasets,
		Total:  int(total),
		Offset: params.Offset,
		Limit:  params.Limit,
	}, nil
}

func (r *DatasetRepo) Update(ctx context.Context, params UpdateDatasetParams) (*Dataset, error) {
	row, err := r.q.UpdateDataset(ctx, sqlcdb.UpdateDatasetParams{
		Name: params.Name,
		Type: params.Type,
		ID:   params.ID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return &Dataset{
		ID:        row.ID,
		Name:      row.Name,
		Type:      row.Type,
		CreatedAt: row.CreatedAt.Time,
		UpdatedAt: row.UpdatedAt.Time,
	}, nil
}

func (r *DatasetRepo) Delete(ctx context.Context, id uuid.UUID) (bool, error) {
	rows, err := r.q.DeleteDataset(ctx, id)
	if err != nil {
		return false, err
	}
	return rows > 0, nil
}
