package app

import (
	"context"
	"time"

	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

type repoReadyOrphanTxRunner interface {
	InTx(ctx context.Context, fn func(store assetrepo.ReadyOrphanGCTx) error) error
}

type repoReadyOrphanTxRunnerAdapter struct {
	source repoReadyOrphanTxRunner
}

type repoReadyOrphanTxStoreAdapter struct {
	source assetrepo.ReadyOrphanGCTx
}

func NewRepoReadyOrphanTxRunner(source repoReadyOrphanTxRunner) ReadyOrphanTxRunner {
	if source == nil {
		return nil
	}
	return &repoReadyOrphanTxRunnerAdapter{source: source}
}

func (r *repoReadyOrphanTxRunnerAdapter) InTx(ctx context.Context, fn func(store ReadyOrphanTxStore) error) error {
	return r.source.InTx(ctx, func(store assetrepo.ReadyOrphanGCTx) error {
		return fn(repoReadyOrphanTxStoreAdapter{source: store})
	})
}

func (s repoReadyOrphanTxStoreAdapter) LockReadyOrphanedAsset(ctx context.Context, id uuid.UUID, cutoff time.Time) (*Asset, error) {
	asset, err := s.source.LockReadyOrphanedAsset(ctx, id, cutoff)
	if err != nil {
		return nil, err
	}
	return fromRepoAsset(asset)
}

func (s repoReadyOrphanTxStoreAdapter) DeleteAsset(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.source.DeleteAsset(ctx, id)
}
