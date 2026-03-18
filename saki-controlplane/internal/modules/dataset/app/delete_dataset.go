package app

import (
	"context"
	"time"

	"github.com/google/uuid"
)

type DeleteDatasetStore interface {
	Delete(ctx context.Context, id uuid.UUID) (bool, error)
}

type DeleteDatasetTxStore interface {
	HasDataset(ctx context.Context, id uuid.UUID) (bool, error)
	ListSampleIDsByDataset(ctx context.Context, datasetID uuid.UUID) ([]uuid.UUID, error)
	InvalidateAssetReferencesForDataset(ctx context.Context, datasetID uuid.UUID, sampleIDs []uuid.UUID, deletedAt time.Time) error
	DeleteDataset(ctx context.Context, id uuid.UUID) (bool, error)
}

type DeleteDatasetTxRunner interface {
	InTx(ctx context.Context, fn func(store DeleteDatasetTxStore) error) error
}

type DeleteDatasetUseCase struct {
	store DeleteDatasetStore
	tx    DeleteDatasetTxRunner
	now   func() time.Time
}

func NewDeleteDatasetUseCase(store DeleteDatasetStore) *DeleteDatasetUseCase {
	return &DeleteDatasetUseCase{
		store: store,
		now:   time.Now,
	}
}

func NewDeleteDatasetUseCaseWithTx(tx DeleteDatasetTxRunner) *DeleteDatasetUseCase {
	return &DeleteDatasetUseCase{
		tx:  tx,
		now: time.Now,
	}
}

func (u *DeleteDatasetUseCase) Execute(ctx context.Context, id uuid.UUID) (bool, error) {
	if u == nil {
		return false, nil
	}
	if u.tx == nil {
		return u.store.Delete(ctx, id)
	}

	var deleted bool
	err := u.tx.InTx(ctx, func(store DeleteDatasetTxStore) error {
		exists, err := store.HasDataset(ctx, id)
		if err != nil {
			return err
		}
		if !exists {
			deleted = false
			return nil
		}

		sampleIDs, err := store.ListSampleIDsByDataset(ctx, id)
		if err != nil {
			return err
		}
		if err := store.InvalidateAssetReferencesForDataset(ctx, id, sampleIDs, u.nowUTC()); err != nil {
			return err
		}

		deleted, err = store.DeleteDataset(ctx, id)
		return err
	})
	if err != nil {
		return false, err
	}
	return deleted, nil
}

func (u *DeleteDatasetUseCase) nowUTC() time.Time {
	if u.now != nil {
		return u.now().UTC()
	}
	return time.Now().UTC()
}
