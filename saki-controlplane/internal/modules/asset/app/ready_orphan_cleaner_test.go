package app

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/google/uuid"
)

func TestReadyOrphanCleanerDeletesOnlyAssetsPastRetentionWindow(t *testing.T) {
	now := time.Date(2026, 3, 19, 12, 0, 0, 0, time.UTC)
	staleID := uuid.New()
	freshID := uuid.New()
	activeID := uuid.New()

	store := newFakeReadyOrphanStore()
	store.assets[staleID] = Asset{
		ID:             staleID,
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "ready/stale.png",
		OrphanedAt:     timePtr(now.Add(-25 * time.Hour)),
	}
	store.assets[freshID] = Asset{
		ID:             freshID,
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "ready/fresh.png",
		OrphanedAt:     timePtr(now.Add(-2 * time.Hour)),
	}
	store.assets[activeID] = Asset{
		ID:             activeID,
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "ready/active.png",
		OrphanedAt:     timePtr(now.Add(-30 * time.Hour)),
	}
	store.active[activeID] = true

	provider := &fakeReadyOrphanProvider{bucket: "assets"}
	cleaner := NewReadyOrphanCleaner(
		store,
		newFakeReadyOrphanTxRunner(store),
		provider,
		ReadyOrphanCleanerConfig{
			Now:             func() time.Time { return now },
			RetentionWindow: 24 * time.Hour,
		},
	)

	if err := cleaner.RunOnce(context.Background()); err != nil {
		t.Fatalf("run ready orphan cleaner: %v", err)
	}
	if _, ok := store.assets[staleID]; ok {
		t.Fatalf("expected stale ready asset to be deleted")
	}
	if _, ok := store.assets[freshID]; !ok {
		t.Fatalf("expected fresh orphaned asset to be kept")
	}
	if _, ok := store.assets[activeID]; !ok {
		t.Fatalf("expected active-referenced asset to be kept")
	}
	if got, want := provider.deletedObjectKeys, []string{"ready/stale.png"}; len(got) != len(want) || got[0] != want[0] {
		t.Fatalf("deleted object keys got %v want %v", got, want)
	}
	if got, want := store.lastCutoff, now.Add(-24*time.Hour); !got.Equal(want) {
		t.Fatalf("cutoff got %v want %v", got, want)
	}
}

func TestReadyOrphanCleanerSkipsAssetWhenRecheckNoLongerMatches(t *testing.T) {
	now := time.Date(2026, 3, 19, 12, 0, 0, 0, time.UTC)
	assetID := uuid.New()

	store := newFakeReadyOrphanStore()
	store.assets[assetID] = Asset{
		ID:             assetID,
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "ready/rebound.png",
		OrphanedAt:     timePtr(now.Add(-26 * time.Hour)),
	}
	store.recheckMiss[assetID] = true

	provider := &fakeReadyOrphanProvider{bucket: "assets"}
	cleaner := NewReadyOrphanCleaner(
		store,
		newFakeReadyOrphanTxRunner(store),
		provider,
		ReadyOrphanCleanerConfig{
			Now:             func() time.Time { return now },
			RetentionWindow: 24 * time.Hour,
		},
	)

	if err := cleaner.RunOnce(context.Background()); err != nil {
		t.Fatalf("run ready orphan cleaner: %v", err)
	}
	if _, ok := store.assets[assetID]; !ok {
		t.Fatalf("expected asset to remain when recheck no longer matches")
	}
	if len(provider.deletedObjectKeys) != 0 {
		t.Fatalf("expected no object deletion when recheck misses, got %v", provider.deletedObjectKeys)
	}
}

func TestReadyOrphanCleanerDoesNotDeleteAssetWhenObjectDeleteFails(t *testing.T) {
	now := time.Date(2026, 3, 19, 12, 0, 0, 0, time.UTC)
	assetID := uuid.New()

	store := newFakeReadyOrphanStore()
	store.assets[assetID] = Asset{
		ID:             assetID,
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "ready/failing.png",
		OrphanedAt:     timePtr(now.Add(-26 * time.Hour)),
	}

	cleaner := NewReadyOrphanCleaner(
		store,
		newFakeReadyOrphanTxRunner(store),
		&fakeReadyOrphanProvider{
			bucket:    "assets",
			deleteErr: errors.New("delete failed"),
		},
		ReadyOrphanCleanerConfig{
			Now:             func() time.Time { return now },
			RetentionWindow: 24 * time.Hour,
		},
	)

	if err := cleaner.RunOnce(context.Background()); err == nil {
		t.Fatal("expected cleaner to report object delete failure")
	}
	if _, ok := store.assets[assetID]; !ok {
		t.Fatalf("expected asset row to remain when object delete fails")
	}
	if len(store.deletedAssetIDs) != 0 {
		t.Fatalf("expected asset row delete to be skipped, got %v", store.deletedAssetIDs)
	}
}

func TestReadyOrphanCleanerTreatsMissingObjectAsDeletable(t *testing.T) {
	now := time.Date(2026, 3, 19, 12, 0, 0, 0, time.UTC)
	assetID := uuid.New()

	store := newFakeReadyOrphanStore()
	store.assets[assetID] = Asset{
		ID:             assetID,
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "ready/missing.png",
		OrphanedAt:     timePtr(now.Add(-26 * time.Hour)),
	}

	cleaner := NewReadyOrphanCleaner(
		store,
		newFakeReadyOrphanTxRunner(store),
		&fakeReadyOrphanProvider{
			bucket:    "assets",
			deleteErr: storage.ErrObjectNotFound,
		},
		ReadyOrphanCleanerConfig{
			Now:             func() time.Time { return now },
			RetentionWindow: 24 * time.Hour,
		},
	)

	if err := cleaner.RunOnce(context.Background()); err != nil {
		t.Fatalf("run ready orphan cleaner: %v", err)
	}
	if _, ok := store.assets[assetID]; ok {
		t.Fatalf("expected asset row to be deleted when object is already missing")
	}
}

type fakeReadyOrphanProvider struct {
	bucket            string
	deletedObjectKeys []string
	deleteErr         error
}

func (p *fakeReadyOrphanProvider) Bucket() string { return p.bucket }

func (p *fakeReadyOrphanProvider) SignPutObject(context.Context, string, time.Duration, string) (string, error) {
	return "", errors.New("not implemented")
}

func (p *fakeReadyOrphanProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", errors.New("not implemented")
}

func (p *fakeReadyOrphanProvider) StatObject(context.Context, string) (*storage.ObjectStat, error) {
	return nil, errors.New("not implemented")
}

func (p *fakeReadyOrphanProvider) DownloadObject(context.Context, string, string) error {
	return errors.New("not implemented")
}

func (p *fakeReadyOrphanProvider) DeleteObject(_ context.Context, objectKey string) error {
	if p.deleteErr != nil {
		return p.deleteErr
	}
	p.deletedObjectKeys = append(p.deletedObjectKeys, objectKey)
	return nil
}

type fakeReadyOrphanStore struct {
	assets          map[uuid.UUID]Asset
	active          map[uuid.UUID]bool
	recheckMiss     map[uuid.UUID]bool
	lastCutoff      time.Time
	deletedAssetIDs []uuid.UUID
	lockedCandidate []uuid.UUID
}

func newFakeReadyOrphanStore() *fakeReadyOrphanStore {
	return &fakeReadyOrphanStore{
		assets:      make(map[uuid.UUID]Asset),
		active:      make(map[uuid.UUID]bool),
		recheckMiss: make(map[uuid.UUID]bool),
	}
}

func (s *fakeReadyOrphanStore) ListReadyOrphaned(_ context.Context, cutoff time.Time) ([]Asset, error) {
	s.lastCutoff = cutoff

	var assets []Asset
	for _, asset := range s.assets {
		if asset.Status != AssetStatusReady || asset.OrphanedAt == nil || asset.OrphanedAt.After(cutoff) {
			continue
		}
		if s.active[asset.ID] {
			continue
		}
		assets = append(assets, cloneAssetForReadyOrphan(asset))
	}
	return assets, nil
}

type fakeReadyOrphanTxRunner struct {
	store *fakeReadyOrphanStore
}

func newFakeReadyOrphanTxRunner(store *fakeReadyOrphanStore) *fakeReadyOrphanTxRunner {
	return &fakeReadyOrphanTxRunner{store: store}
}

func (r *fakeReadyOrphanTxRunner) InTx(ctx context.Context, fn func(store ReadyOrphanTxStore) error) error {
	return fn(fakeReadyOrphanTxStore{store: r.store})
}

type fakeReadyOrphanTxStore struct {
	store *fakeReadyOrphanStore
}

func (s fakeReadyOrphanTxStore) LockReadyOrphanedAsset(_ context.Context, id uuid.UUID, cutoff time.Time) (*Asset, error) {
	asset, ok := s.store.assets[id]
	if !ok {
		return nil, nil
	}
	if s.store.recheckMiss[id] || s.store.active[id] {
		return nil, nil
	}
	if asset.Status != AssetStatusReady || asset.OrphanedAt == nil || asset.OrphanedAt.After(cutoff) {
		return nil, nil
	}
	s.store.lockedCandidate = append(s.store.lockedCandidate, id)
	locked := cloneAssetForReadyOrphan(asset)
	return &locked, nil
}

func (s fakeReadyOrphanTxStore) DeleteAsset(_ context.Context, id uuid.UUID) (bool, error) {
	if _, ok := s.store.assets[id]; !ok {
		return false, nil
	}
	delete(s.store.assets, id)
	s.store.deletedAssetIDs = append(s.store.deletedAssetIDs, id)
	return true, nil
}

func timePtr(v time.Time) *time.Time {
	return &v
}

func cloneAssetForReadyOrphan(asset Asset) Asset {
	cloned := asset
	cloned.Sha256Hex = cloneStringPtr(asset.Sha256Hex)
	cloned.Metadata = cloneBytes(asset.Metadata)
	cloned.CreatedBy = cloneUUIDPtr(asset.CreatedBy)
	cloned.ReadyAt = cloneTimePtr(asset.ReadyAt)
	cloned.OrphanedAt = cloneTimePtr(asset.OrphanedAt)
	return cloned
}
