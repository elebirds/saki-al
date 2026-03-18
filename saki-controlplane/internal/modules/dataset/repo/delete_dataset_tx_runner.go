package repo

import (
	"context"
	"errors"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type DeleteDatasetTx interface {
	HasDataset(ctx context.Context, id uuid.UUID) (bool, error)
	ListSampleIDsByDataset(ctx context.Context, datasetID uuid.UUID) ([]uuid.UUID, error)
	InvalidateAssetReferencesForDataset(ctx context.Context, datasetID uuid.UUID, sampleIDs []uuid.UUID, deletedAt time.Time) error
	DeleteDataset(ctx context.Context, id uuid.UUID) (bool, error)
}

type DeleteDatasetTxRunner struct {
	tx *appdb.TxRunner
}

func NewDeleteDatasetTxRunner(pool *pgxpool.Pool) *DeleteDatasetTxRunner {
	return &DeleteDatasetTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *DeleteDatasetTxRunner) InTx(ctx context.Context, fn func(store DeleteDatasetTx) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		return fn(deleteDatasetTxStore{q: sqlcdb.New(tx)})
	})
}

type deleteDatasetTxStore struct {
	q *sqlcdb.Queries
}

func (s deleteDatasetTxStore) HasDataset(ctx context.Context, id uuid.UUID) (bool, error) {
	_, err := s.q.GetDatasetForUpdate(ctx, id)
	if err == nil {
		return true, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return false, err
}

func (s deleteDatasetTxStore) ListSampleIDsByDataset(ctx context.Context, datasetID uuid.UUID) ([]uuid.UUID, error) {
	return s.q.ListSampleIDsByDataset(ctx, datasetID)
}

func (s deleteDatasetTxStore) InvalidateAssetReferencesForDataset(ctx context.Context, datasetID uuid.UUID, sampleIDs []uuid.UUID, deletedAt time.Time) error {
	if _, err := s.q.InvalidateAssetReferencesForOwner(ctx, sqlcdb.InvalidateAssetReferencesForOwnerParams{
		OwnerType: sqlcdb.AssetOwnerTypeDataset,
		OwnerID:   datasetID,
		DeletedAt: pgTime(deletedAt),
	}); err != nil {
		return err
	}

	for _, sampleID := range sampleIDs {
		if _, err := s.q.InvalidateAssetReferencesForOwner(ctx, sqlcdb.InvalidateAssetReferencesForOwnerParams{
			OwnerType: sqlcdb.AssetOwnerTypeSample,
			OwnerID:   sampleID,
			DeletedAt: pgTime(deletedAt),
		}); err != nil {
			return err
		}
	}
	return nil
}

func (s deleteDatasetTxStore) DeleteDataset(ctx context.Context, id uuid.UUID) (bool, error) {
	rows, err := s.q.DeleteDataset(ctx, id)
	if err != nil {
		return false, err
	}
	return rows > 0, nil
}

func pgTime(t time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{
		Time:  t.UTC(),
		Valid: true,
	}
}
