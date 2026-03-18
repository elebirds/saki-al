package app

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

type ReadyOrphanStore interface {
	ListReadyOrphaned(ctx context.Context, cutoff time.Time) ([]Asset, error)
}

type ReadyOrphanTxStore interface {
	LockReadyOrphanedAsset(ctx context.Context, id uuid.UUID, cutoff time.Time) (*Asset, error)
	DeleteAsset(ctx context.Context, id uuid.UUID) (bool, error)
}

type ReadyOrphanTxRunner interface {
	InTx(ctx context.Context, fn func(store ReadyOrphanTxStore) error) error
}

type ReadyOrphanCleanerConfig struct {
	Now             func() time.Time
	RetentionWindow time.Duration
}

type ReadyOrphanCleaner struct {
	store    ReadyOrphanStore
	tx       ReadyOrphanTxRunner
	provider storage.Provider
	config   ReadyOrphanCleanerConfig
}

type readyOrphanRepoReader interface {
	ListReadyOrphaned(ctx context.Context, params assetrepo.ListReadyOrphanedAssetsParams) ([]assetrepo.Asset, error)
}

type repoReadyOrphanStore struct {
	source readyOrphanRepoReader
}

func NewRepoReadyOrphanStore(source readyOrphanRepoReader) ReadyOrphanStore {
	if source == nil {
		return nil
	}
	return &repoReadyOrphanStore{source: source}
}

func NewReadyOrphanCleaner(store ReadyOrphanStore, tx ReadyOrphanTxRunner, provider storage.Provider, config ReadyOrphanCleanerConfig) *ReadyOrphanCleaner {
	return &ReadyOrphanCleaner{
		store:    store,
		tx:       tx,
		provider: provider,
		config:   config,
	}
}

func (s *repoReadyOrphanStore) ListReadyOrphaned(ctx context.Context, cutoff time.Time) ([]Asset, error) {
	rows, err := s.source.ListReadyOrphaned(ctx, assetrepo.ListReadyOrphanedAssetsParams{
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

func (c *ReadyOrphanCleaner) RunOnce(ctx context.Context) error {
	if c == nil || c.store == nil || c.tx == nil {
		return nil
	}

	cutoff := c.config.now().Add(-c.config.retentionWindow())
	assets, err := c.store.ListReadyOrphaned(ctx, cutoff)
	if err != nil {
		return err
	}

	var firstErr error
	for i := range assets {
		if ctx.Err() != nil {
			return ctx.Err()
		}

		assetID := assets[i].ID
		err := c.tx.InTx(ctx, func(store ReadyOrphanTxStore) error {
			locked, err := store.LockReadyOrphanedAsset(ctx, assetID, cutoff)
			if err != nil {
				return err
			}
			if locked == nil {
				return nil
			}
			if err := c.deleteObject(ctx, *locked); err != nil {
				return err
			}
			_, err = store.DeleteAsset(ctx, locked.ID)
			return err
		})
		if err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func (c *ReadyOrphanCleaner) deleteObject(ctx context.Context, asset Asset) error {
	if c.provider == nil {
		return errors.New("ready orphan cleaner requires object storage provider")
	}
	if asset.Bucket != c.provider.Bucket() {
		return fmt.Errorf("ready orphan asset bucket mismatch: asset=%s provider=%s", asset.Bucket, c.provider.Bucket())
	}

	deleter, ok := c.provider.(objectDeleter)
	if !ok {
		return errors.New("ready orphan cleaner provider cannot delete objects")
	}
	if err := deleter.DeleteObject(ctx, asset.ObjectKey); err != nil && !errors.Is(err, storage.ErrObjectNotFound) {
		return err
	}
	return nil
}

func (c ReadyOrphanCleanerConfig) now() time.Time {
	if c.Now != nil {
		return c.Now().UTC()
	}
	return time.Now().UTC()
}

func (c ReadyOrphanCleanerConfig) retentionWindow() time.Duration {
	if c.RetentionWindow > 0 {
		return c.RetentionWindow
	}
	return 24 * time.Hour
}
