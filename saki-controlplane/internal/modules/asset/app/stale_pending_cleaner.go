package app

import (
	"context"
	"errors"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

type StalePendingStore interface {
	ListStalePending(ctx context.Context, now time.Time, cutoff time.Time) ([]Asset, error)
	Delete(ctx context.Context, id uuid.UUID) (bool, error)
}

type StalePendingCleanerConfig struct {
	Now               func() time.Time
	UploadGraceWindow time.Duration
}

type StalePendingCleaner struct {
	store    StalePendingStore
	provider storage.Provider
	config   StalePendingCleanerConfig
}

type stalePendingRepoReader interface {
	ListStalePending(ctx context.Context, params assetrepo.ListStalePendingAssetsParams) ([]assetrepo.Asset, error)
	Delete(ctx context.Context, id uuid.UUID) (bool, error)
}

type repoStalePendingStore struct {
	source stalePendingRepoReader
}

type objectDeleter interface {
	DeleteObject(ctx context.Context, objectKey string) error
}

func NewRepoStalePendingStore(source stalePendingRepoReader) StalePendingStore {
	if source == nil {
		return nil
	}
	return &repoStalePendingStore{source: source}
}

func NewStalePendingCleaner(store StalePendingStore, provider storage.Provider, config StalePendingCleanerConfig) *StalePendingCleaner {
	return &StalePendingCleaner{
		store:    store,
		provider: provider,
		config:   config,
	}
}

func (s *repoStalePendingStore) ListStalePending(ctx context.Context, now time.Time, cutoff time.Time) ([]Asset, error) {
	rows, err := s.source.ListStalePending(ctx, assetrepo.ListStalePendingAssetsParams{
		Now:    now,
		Cutoff: cutoff,
	})
	if err != nil {
		return nil, err
	}

	assets := make([]Asset, 0, len(rows))
	for i := range rows {
		asset, err := fromRepoAsset(&rows[i])
		if err != nil {
			return nil, err
		}
		if asset != nil {
			assets = append(assets, *asset)
		}
	}
	return assets, nil
}

func (s *repoStalePendingStore) Delete(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.source.Delete(ctx, id)
}

func (c *StalePendingCleaner) RunOnce(ctx context.Context) error {
	if c == nil || c.store == nil {
		return nil
	}

	now := c.config.now()
	cutoff := now.Add(-c.config.uploadGraceWindow())
	assets, err := c.store.ListStalePending(ctx, now, cutoff)
	if err != nil {
		return err
	}

	var firstErr error
	for i := range assets {
		if ctx.Err() != nil {
			return ctx.Err()
		}

		asset := assets[i]
		c.deleteObjectBestEffort(ctx, asset)
		if _, err := c.store.Delete(ctx, asset.ID); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func (c *StalePendingCleaner) deleteObjectBestEffort(ctx context.Context, asset Asset) {
	if c.provider == nil || asset.Bucket != c.provider.Bucket() {
		return
	}
	deleter, ok := c.provider.(objectDeleter)
	if !ok {
		return
	}
	err := deleter.DeleteObject(ctx, asset.ObjectKey)
	if err == nil || errors.Is(err, storage.ErrObjectNotFound) {
		return
	}
}

func (c StalePendingCleanerConfig) now() time.Time {
	if c.Now != nil {
		return c.Now().UTC()
	}
	return time.Now().UTC()
}

func (c StalePendingCleanerConfig) uploadGraceWindow() time.Duration {
	if c.UploadGraceWindow > 0 {
		return c.UploadGraceWindow
	}
	return 30 * time.Minute
}
