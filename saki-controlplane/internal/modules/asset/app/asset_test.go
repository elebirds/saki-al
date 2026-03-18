package app

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/google/uuid"
)

func TestNewRepoStoreMapsRepoAssetToTypedAsset(t *testing.T) {
	id := uuid.New()
	createdBy := uuid.New()
	now := time.Now().UTC().Round(time.Second)
	sha := "deadbeef"

	store := NewRepoStore(&stubRepoGetter{
		asset: &assetrepo.Asset{
			ID:             id,
			Kind:           string(AssetKindImage),
			Status:         string(AssetStatusReady),
			StorageBackend: string(AssetStorageBackendMinio),
			Bucket:         "assets",
			ObjectKey:      "image/demo.png",
			ContentType:    "image/png",
			SizeBytes:      128,
			Sha256Hex:      &sha,
			Metadata:       []byte(`{"source":"test"}`),
			CreatedBy:      &createdBy,
			ReadyAt:        &now,
			CreatedAt:      now,
			UpdatedAt:      now,
		},
	})

	asset, err := store.Get(context.Background(), id)
	if err != nil {
		t.Fatalf("get asset: %v", err)
	}
	if asset == nil {
		t.Fatal("expected asset, got nil")
	}
	if asset.Kind != AssetKindImage {
		t.Fatalf("kind got %q want %q", asset.Kind, AssetKindImage)
	}
	if asset.Status != AssetStatusReady {
		t.Fatalf("status got %q want %q", asset.Status, AssetStatusReady)
	}
	if asset.StorageBackend != AssetStorageBackendMinio {
		t.Fatalf("storage backend got %q want %q", asset.StorageBackend, AssetStorageBackendMinio)
	}
	if asset.Sha256Hex == nil || *asset.Sha256Hex != sha {
		t.Fatalf("sha256 got %v want %q", asset.Sha256Hex, sha)
	}
	if asset.CreatedBy == nil || *asset.CreatedBy != createdBy {
		t.Fatalf("created by got %v want %v", asset.CreatedBy, createdBy)
	}
	if asset.ReadyAt == nil || !asset.ReadyAt.Equal(now) {
		t.Fatalf("ready at got %v want %v", asset.ReadyAt, now)
	}
}

func TestNewRepoStoreRejectsInvalidTypedValues(t *testing.T) {
	id := uuid.New()
	store := NewRepoStore(&stubRepoGetter{
		asset: &assetrepo.Asset{
			ID:             id,
			Kind:           string(AssetKindImage),
			Status:         "broken",
			StorageBackend: string(AssetStorageBackendMinio),
			Bucket:         "assets",
			ObjectKey:      "image/demo.png",
			ContentType:    "image/png",
		},
	})

	asset, err := store.Get(context.Background(), id)
	if !errors.Is(err, ErrInvalidAssetStatus) {
		t.Fatalf("expected ErrInvalidAssetStatus, got asset=%+v err=%v", asset, err)
	}
}

func TestIssueUploadTicketRequiresPendingAsset(t *testing.T) {
	assetID := uuid.New()
	store := &stubStore{
		asset: &Asset{
			ID:          assetID,
			Bucket:      "assets",
			Status:      AssetStatusReady,
			ContentType: "image/png",
			ObjectKey:   "assets/demo.png",
		},
	}
	provider := &stubProvider{
		bucket: "assets",
		putURL: "https://example.test/upload",
	}

	uc := NewIssueUploadTicketUseCase(store, provider, 5*time.Minute)
	ticket, err := uc.Execute(context.Background(), assetID)
	if !errors.Is(err, ErrAssetNotPendingUpload) {
		t.Fatalf("expected ErrAssetNotPendingUpload, got ticket=%+v err=%v", ticket, err)
	}

	store.asset.Status = AssetStatusPendingUpload
	ticket, err = uc.Execute(context.Background(), assetID)
	if err != nil {
		t.Fatalf("issue upload ticket: %v", err)
	}
	if ticket == nil || ticket.URL != "https://example.test/upload" {
		t.Fatalf("unexpected upload ticket: %+v", ticket)
	}
	if got, want := provider.lastPutObjectKey, "assets/demo.png"; got != want {
		t.Fatalf("provider object key got %q want %q", got, want)
	}
	if got, want := provider.lastPutContentType, "image/png"; got != want {
		t.Fatalf("provider content type got %q want %q", got, want)
	}

	store.asset.Bucket = "other-bucket"
	ticket, err = uc.Execute(context.Background(), assetID)
	if !errors.Is(err, ErrAssetBucketMismatch) {
		t.Fatalf("expected ErrAssetBucketMismatch, got ticket=%+v err=%v", ticket, err)
	}
}

func TestIssueDownloadTicketRequiresReadyAsset(t *testing.T) {
	assetID := uuid.New()
	store := &stubStore{
		asset: &Asset{
			ID:        assetID,
			Bucket:    "assets",
			Status:    AssetStatusPendingUpload,
			ObjectKey: "assets/demo.png",
		},
	}
	provider := &stubProvider{
		bucket: "assets",
		getURL: "https://example.test/download",
	}

	uc := NewIssueDownloadTicketUseCase(store, provider, 5*time.Minute)
	ticket, err := uc.Execute(context.Background(), assetID)
	if !errors.Is(err, ErrAssetNotReady) {
		t.Fatalf("expected ErrAssetNotReady, got ticket=%+v err=%v", ticket, err)
	}

	store.asset.Status = AssetStatusReady
	ticket, err = uc.Execute(context.Background(), assetID)
	if err != nil {
		t.Fatalf("issue download ticket: %v", err)
	}
	if ticket == nil || ticket.URL != "https://example.test/download" {
		t.Fatalf("unexpected download ticket: %+v", ticket)
	}
	if got, want := provider.lastGetObjectKey, "assets/demo.png"; got != want {
		t.Fatalf("provider object key got %q want %q", got, want)
	}

	store.asset.Bucket = "other-bucket"
	ticket, err = uc.Execute(context.Background(), assetID)
	if !errors.Is(err, ErrAssetBucketMismatch) {
		t.Fatalf("expected ErrAssetBucketMismatch, got ticket=%+v err=%v", ticket, err)
	}
}

type stubStore struct {
	asset *Asset
	err   error
}

type stubRepoGetter struct {
	asset *assetrepo.Asset
	err   error
}

func (s *stubRepoGetter) Get(_ context.Context, id uuid.UUID) (*assetrepo.Asset, error) {
	if s.err != nil {
		return nil, s.err
	}
	if s.asset == nil || s.asset.ID != id {
		return nil, nil
	}
	copy := *s.asset
	return &copy, nil
}

func (s *stubStore) Get(_ context.Context, id uuid.UUID) (*Asset, error) {
	if s.err != nil {
		return nil, s.err
	}
	if s.asset == nil || s.asset.ID != id {
		return nil, nil
	}
	copy := *s.asset
	return &copy, nil
}

type stubProvider struct {
	bucket             string
	putURL             string
	getURL             string
	lastPutObjectKey   string
	lastPutContentType string
	lastGetObjectKey   string
}

func (p *stubProvider) Bucket() string {
	return p.bucket
}

func (p *stubProvider) SignPutObject(_ context.Context, objectKey string, _ time.Duration, contentType string) (string, error) {
	p.lastPutObjectKey = objectKey
	p.lastPutContentType = contentType
	return p.putURL, nil
}

func (p *stubProvider) SignGetObject(_ context.Context, objectKey string, _ time.Duration) (string, error) {
	p.lastGetObjectKey = objectKey
	return p.getURL, nil
}

func (p *stubProvider) StatObject(context.Context, string) (*storage.ObjectStat, error) {
	return nil, nil
}

func (p *stubProvider) DownloadObject(context.Context, string, string) error {
	return nil
}
