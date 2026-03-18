package app

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
)

var ErrSampleDatasetMismatch = errors.New("sample does not belong to dataset")

type DeleteSampleRecord struct {
	ID        uuid.UUID
	DatasetID uuid.UUID
}

type DeleteSampleTxStore interface {
	GetSampleForUpdate(ctx context.Context, sampleID uuid.UUID) (*DeleteSampleRecord, error)
	InvalidateAssetReferencesForSample(ctx context.Context, sampleID uuid.UUID, deletedAt time.Time) error
	DeleteSample(ctx context.Context, sampleID uuid.UUID) (bool, error)
}

type DeleteSampleTxRunner interface {
	InTx(ctx context.Context, fn func(store DeleteSampleTxStore) error) error
}

type DeleteSampleUseCase struct {
	tx  DeleteSampleTxRunner
	now func() time.Time
}

func NewDeleteSampleUseCaseWithTx(tx DeleteSampleTxRunner) *DeleteSampleUseCase {
	return &DeleteSampleUseCase{
		tx:  tx,
		now: time.Now,
	}
}

func (u *DeleteSampleUseCase) Execute(ctx context.Context, datasetID, sampleID uuid.UUID) (bool, error) {
	if u == nil || u.tx == nil {
		return false, nil
	}

	var deleted bool
	err := u.tx.InTx(ctx, func(store DeleteSampleTxStore) error {
		sample, err := store.GetSampleForUpdate(ctx, sampleID)
		if err != nil {
			return err
		}
		if sample == nil {
			deleted = false
			return nil
		}
		if sample.DatasetID != datasetID {
			return ErrSampleDatasetMismatch
		}
		if err := store.InvalidateAssetReferencesForSample(ctx, sampleID, u.nowUTC()); err != nil {
			return err
		}

		deleted, err = store.DeleteSample(ctx, sampleID)
		return err
	})
	if err != nil {
		return false, err
	}
	return deleted, nil
}

func (u *DeleteSampleUseCase) nowUTC() time.Time {
	if u.now != nil {
		return u.now().UTC()
	}
	return time.Now().UTC()
}
