package app

import (
	"context"
	"time"

	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	"github.com/google/uuid"
)

type repoDeleteDatasetTxRunner interface {
	InTx(ctx context.Context, fn func(store datasetrepo.DeleteDatasetTx) error) error
}

type repoDeleteDatasetTxRunnerAdapter struct {
	source repoDeleteDatasetTxRunner
}

type repoDeleteDatasetTxStoreAdapter struct {
	source datasetrepo.DeleteDatasetTx
}

func NewRepoDeleteDatasetTxRunner(source repoDeleteDatasetTxRunner) DeleteDatasetTxRunner {
	if source == nil {
		return nil
	}
	return &repoDeleteDatasetTxRunnerAdapter{source: source}
}

func (r *repoDeleteDatasetTxRunnerAdapter) InTx(ctx context.Context, fn func(store DeleteDatasetTxStore) error) error {
	return r.source.InTx(ctx, func(store datasetrepo.DeleteDatasetTx) error {
		return fn(repoDeleteDatasetTxStoreAdapter{source: store})
	})
}

func (s repoDeleteDatasetTxStoreAdapter) HasDataset(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.source.HasDataset(ctx, id)
}

func (s repoDeleteDatasetTxStoreAdapter) ListSampleIDsByDataset(ctx context.Context, datasetID uuid.UUID) ([]uuid.UUID, error) {
	return s.source.ListSampleIDsByDataset(ctx, datasetID)
}

func (s repoDeleteDatasetTxStoreAdapter) InvalidateAssetReferencesForDataset(ctx context.Context, datasetID uuid.UUID, sampleIDs []uuid.UUID, deletedAt time.Time) error {
	return s.source.InvalidateAssetReferencesForDataset(ctx, datasetID, sampleIDs, deletedAt)
}

func (s repoDeleteDatasetTxStoreAdapter) DeleteDataset(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.source.DeleteDataset(ctx, id)
}
