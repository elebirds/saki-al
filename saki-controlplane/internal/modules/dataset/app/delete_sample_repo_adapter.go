package app

import (
	"context"
	"time"

	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	"github.com/google/uuid"
)

type repoDeleteSampleTxRunner interface {
	InTx(ctx context.Context, fn func(store datasetrepo.DeleteSampleTx) error) error
}

type repoDeleteSampleTxRunnerAdapter struct {
	source repoDeleteSampleTxRunner
}

type repoDeleteSampleTxStoreAdapter struct {
	source datasetrepo.DeleteSampleTx
}

func NewRepoDeleteSampleTxRunner(source repoDeleteSampleTxRunner) DeleteSampleTxRunner {
	if source == nil {
		return nil
	}
	return &repoDeleteSampleTxRunnerAdapter{source: source}
}

func (r *repoDeleteSampleTxRunnerAdapter) InTx(ctx context.Context, fn func(store DeleteSampleTxStore) error) error {
	return r.source.InTx(ctx, func(store datasetrepo.DeleteSampleTx) error {
		return fn(repoDeleteSampleTxStoreAdapter{source: store})
	})
}

func (s repoDeleteSampleTxStoreAdapter) GetSampleForUpdate(ctx context.Context, sampleID uuid.UUID) (*DeleteSampleRecord, error) {
	row, err := s.source.GetSampleForUpdate(ctx, sampleID)
	if err != nil || row == nil {
		return nil, err
	}
	return &DeleteSampleRecord{
		ID:        row.ID,
		DatasetID: row.DatasetID,
	}, nil
}

func (s repoDeleteSampleTxStoreAdapter) InvalidateAssetReferencesForSample(ctx context.Context, sampleID uuid.UUID, deletedAt time.Time) error {
	return s.source.InvalidateAssetReferencesForSample(ctx, sampleID, deletedAt)
}

func (s repoDeleteSampleTxStoreAdapter) DeleteSample(ctx context.Context, sampleID uuid.UUID) (bool, error) {
	return s.source.DeleteSample(ctx, sampleID)
}
