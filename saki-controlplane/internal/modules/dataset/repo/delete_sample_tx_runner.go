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

type DeleteSampleRecord struct {
	ID        uuid.UUID
	DatasetID uuid.UUID
}

type DeleteSampleTx interface {
	GetSampleForUpdate(ctx context.Context, sampleID uuid.UUID) (*DeleteSampleRecord, error)
	InvalidateAssetReferencesForSample(ctx context.Context, sampleID uuid.UUID, deletedAt time.Time) error
	DeleteSample(ctx context.Context, sampleID uuid.UUID) (bool, error)
}

type DeleteSampleTxRunner struct {
	tx *appdb.TxRunner
}

func NewDeleteSampleTxRunner(pool *pgxpool.Pool) *DeleteSampleTxRunner {
	return &DeleteSampleTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *DeleteSampleTxRunner) InTx(ctx context.Context, fn func(store DeleteSampleTx) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		return fn(deleteSampleTxStore{q: sqlcdb.New(tx)})
	})
}

type deleteSampleTxStore struct {
	q *sqlcdb.Queries
}

func (s deleteSampleTxStore) GetSampleForUpdate(ctx context.Context, sampleID uuid.UUID) (*DeleteSampleRecord, error) {
	row, err := s.q.GetSampleForUpdate(ctx, sampleID)
	if err == nil {
		return &DeleteSampleRecord{
			ID:        row.ID,
			DatasetID: row.DatasetID,
		}, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return nil, err
}

func (s deleteSampleTxStore) InvalidateAssetReferencesForSample(ctx context.Context, sampleID uuid.UUID, deletedAt time.Time) error {
	_, err := s.q.InvalidateAssetReferencesForOwner(ctx, sqlcdb.InvalidateAssetReferencesForOwnerParams{
		OwnerType: sqlcdb.AssetOwnerTypeSample,
		OwnerID:   sampleID,
		DeletedAt: pgTime(deletedAt),
	})
	return err
}

func (s deleteSampleTxStore) DeleteSample(ctx context.Context, sampleID uuid.UUID) (bool, error) {
	rows, err := s.q.DeleteSample(ctx, sampleID)
	if err != nil {
		return false, err
	}
	return rows > 0, nil
}
