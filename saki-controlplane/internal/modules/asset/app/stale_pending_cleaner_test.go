package app

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/google/uuid"
)

func TestStalePendingCleanerDeletesOnlyPastGraceWindowAssets(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	staleAssetID := uuid.New()
	freshAssetID := uuid.New()
	readyAssetID := uuid.New()
	store := &fakeStalePendingStore{
		assets: map[uuid.UUID]Asset{
			staleAssetID: {
				ID:             staleAssetID,
				Kind:           AssetKindArchive,
				Status:         AssetStatusPendingUpload,
				StorageBackend: AssetStorageBackendMinio,
				Bucket:         "assets",
				ObjectKey:      "archive/stale",
				CreatedAt:      now.Add(-31 * time.Minute),
			},
			freshAssetID: {
				ID:             freshAssetID,
				Kind:           AssetKindArchive,
				Status:         AssetStatusPendingUpload,
				StorageBackend: AssetStorageBackendMinio,
				Bucket:         "assets",
				ObjectKey:      "archive/fresh",
				CreatedAt:      now.Add(-10 * time.Minute),
			},
			readyAssetID: {
				ID:             readyAssetID,
				Kind:           AssetKindArchive,
				Status:         AssetStatusReady,
				StorageBackend: AssetStorageBackendMinio,
				Bucket:         "assets",
				ObjectKey:      "archive/ready",
				CreatedAt:      now.Add(-40 * time.Minute),
			},
		},
	}
	provider := &fakeCleanerProvider{bucket: "assets"}
	cleaner := NewStalePendingCleaner(store, provider, StalePendingCleanerConfig{
		Now:               func() time.Time { return now },
		UploadGraceWindow: 30 * time.Minute,
	})

	if err := cleaner.RunOnce(context.Background()); err != nil {
		t.Fatalf("run stale pending cleaner: %v", err)
	}
	if _, ok := store.assets[staleAssetID]; ok {
		t.Fatalf("expected stale asset to be deleted")
	}
	if _, ok := store.assets[freshAssetID]; !ok {
		t.Fatalf("expected fresh asset to be kept")
	}
	if _, ok := store.assets[readyAssetID]; !ok {
		t.Fatalf("expected ready asset to be kept")
	}
	if got, want := provider.deletedObjectKeys, []string{"archive/stale"}; len(got) != len(want) || got[0] != want[0] {
		t.Fatalf("deleted object keys got %v want %v", got, want)
	}
	if got, want := store.lastCutoff, now.Add(-30*time.Minute); !got.Equal(want) {
		t.Fatalf("cutoff got %v want %v", got, want)
	}
}

func TestStalePendingCleanerDeletesAssetAndCascadesIntent(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	assetID := uuid.New()
	store := &fakeStalePendingStore{
		assets: map[uuid.UUID]Asset{
			assetID: {
				ID:             assetID,
				Kind:           AssetKindImage,
				Status:         AssetStatusPendingUpload,
				StorageBackend: AssetStorageBackendMinio,
				Bucket:         "assets",
				ObjectKey:      "image/cascade",
				CreatedAt:      now.Add(-31 * time.Minute),
			},
		},
		intentAssetIDs: map[uuid.UUID]struct{}{
			assetID: {},
		},
	}
	cleaner := NewStalePendingCleaner(store, &fakeCleanerProvider{bucket: "assets"}, StalePendingCleanerConfig{
		Now:               func() time.Time { return now },
		UploadGraceWindow: 30 * time.Minute,
	})

	if err := cleaner.RunOnce(context.Background()); err != nil {
		t.Fatalf("run stale pending cleaner: %v", err)
	}
	if _, ok := store.assets[assetID]; ok {
		t.Fatalf("expected stale asset to be deleted")
	}
	if _, ok := store.intentAssetIDs[assetID]; ok {
		t.Fatalf("expected delete to cascade intent removal")
	}
}

type fakeCleanerProvider struct {
	bucket            string
	deletedObjectKeys []string
	deleteErr         error
}

func (p *fakeCleanerProvider) Bucket() string { return p.bucket }

func (p *fakeCleanerProvider) SignPutObject(context.Context, string, time.Duration, string) (string, error) {
	return "", errors.New("not implemented")
}

func (p *fakeCleanerProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", errors.New("not implemented")
}

func (p *fakeCleanerProvider) StatObject(context.Context, string) (*storage.ObjectStat, error) {
	return nil, errors.New("not implemented")
}

func (p *fakeCleanerProvider) DownloadObject(context.Context, string, string) error {
	return errors.New("not implemented")
}

func (p *fakeCleanerProvider) DeleteObject(_ context.Context, objectKey string) error {
	if p.deleteErr != nil {
		return p.deleteErr
	}
	p.deletedObjectKeys = append(p.deletedObjectKeys, objectKey)
	return nil
}

type fakeStalePendingStore struct {
	assets         map[uuid.UUID]Asset
	intentAssetIDs map[uuid.UUID]struct{}
	lastNow        time.Time
	lastCutoff     time.Time
}

func (s *fakeStalePendingStore) ListStalePending(ctx context.Context, now time.Time, cutoff time.Time) ([]Asset, error) {
	s.lastNow = now
	s.lastCutoff = cutoff

	var assets []Asset
	for _, asset := range s.assets {
		if asset.Status == AssetStatusPendingUpload && !asset.CreatedAt.After(cutoff) {
			assets = append(assets, cloneAsset(asset))
		}
	}
	return assets, nil
}

func (s *fakeStalePendingStore) Delete(_ context.Context, id uuid.UUID) (bool, error) {
	if _, ok := s.assets[id]; !ok {
		return false, nil
	}
	delete(s.assets, id)
	delete(s.intentAssetIDs, id)
	return true, nil
}
