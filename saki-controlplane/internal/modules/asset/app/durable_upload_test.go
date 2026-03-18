package app

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgconn"
)

func TestInitDurableUploadCreatesPendingAssetAndIntent(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeDataset,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
	store.putResolvedOwner(binding)
	provider := &fakeDurableUploadProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	}

	uc := NewInitDurableUploadUseCase(newFakeDurableUploadTxRunner(store), provider, DurableUploadConfig{
		Now:                func() time.Time { return now },
		BuildObjectKey:     deterministicObjectKeyBuilder,
		UploadURLExpiry:    5 * time.Minute,
		IntentTTL:          10 * time.Minute,
		UploadGraceWindow:  30 * time.Minute,
		MaxObjectKeyTrials: 3,
	})

	result, err := uc.Execute(context.Background(), InitDurableUploadInput{
		Binding:             binding,
		Kind:                AssetKindImage,
		DeclaredContentType: "image/png",
		Metadata:            []byte(`{"source":"camera"}`),
		IdempotencyKey:      "idem-init-1",
	})
	if err != nil {
		t.Fatalf("init durable upload: %v", err)
	}
	if result == nil || result.Asset == nil || result.Intent == nil || result.UploadTicket == nil {
		t.Fatalf("unexpected init result: %+v", result)
	}
	if result.Asset.Status != AssetStatusPendingUpload {
		t.Fatalf("asset status got %q want %q", result.Asset.Status, AssetStatusPendingUpload)
	}
	if result.Asset.ObjectKey != "image/object-0" {
		t.Fatalf("object key got %q want %q", result.Asset.ObjectKey, "image/object-0")
	}
	if result.Intent.State != AssetUploadIntentStateInitiated {
		t.Fatalf("intent state got %q want %q", result.Intent.State, AssetUploadIntentStateInitiated)
	}
	if got, want := result.Intent.ExpiresAt, now.Add(10*time.Minute); !got.Equal(want) {
		t.Fatalf("intent expires at got %v want %v", got, want)
	}
	if result.UploadTicket.URL != provider.putURL {
		t.Fatalf("upload url got %q want %q", result.UploadTicket.URL, provider.putURL)
	}
}

func TestInitDurableUploadReplaysInitiatedIntent(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeDataset,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
	store.putResolvedOwner(binding)
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindImage,
		Status:         AssetStatusPendingUpload,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/existing",
		ContentType:    "image/png",
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedAt:      now,
		UpdatedAt:      now,
	})
	intent := store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "image/png",
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      "idem-replay",
		ExpiresAt:           now.Add(10 * time.Minute),
		CreatedAt:           now,
		UpdatedAt:           now,
	})
	provider := &fakeDurableUploadProvider{
		bucket: "assets",
		putURL: "https://object.test/replay",
	}

	uc := NewInitDurableUploadUseCase(newFakeDurableUploadTxRunner(store), provider, DurableUploadConfig{
		Now:                func() time.Time { return now },
		BuildObjectKey:     deterministicObjectKeyBuilder,
		UploadURLExpiry:    5 * time.Minute,
		IntentTTL:          10 * time.Minute,
		UploadGraceWindow:  30 * time.Minute,
		MaxObjectKeyTrials: 3,
	})

	result, err := uc.Execute(context.Background(), InitDurableUploadInput{
		Binding:             binding,
		Kind:                AssetKindImage,
		DeclaredContentType: "image/png",
		Metadata:            []byte(`{"source":"camera"}`),
		IdempotencyKey:      "idem-replay",
	})
	if err != nil {
		t.Fatalf("replay durable upload: %v", err)
	}
	if result.Asset.ID != asset.ID || result.Intent.ID != intent.ID {
		t.Fatalf("expected replay to reuse asset/intent, got asset=%+v intent=%+v", result.Asset, result.Intent)
	}
	if result.UploadTicket == nil || result.UploadTicket.URL != provider.putURL {
		t.Fatalf("unexpected replay upload ticket: %+v", result.UploadTicket)
	}
	if got, want := len(store.assets), 1; got != want {
		t.Fatalf("asset count got %d want %d", got, want)
	}
}

func TestInitDurableUploadRejectsMismatchedIdempotencyContract(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeDataset,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
	store.putResolvedOwner(binding)
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindImage,
		Status:         AssetStatusPendingUpload,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/existing",
		ContentType:    "image/png",
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedAt:      now,
		UpdatedAt:      now,
	})
	store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "image/png",
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      "idem-mismatch",
		ExpiresAt:           now.Add(10 * time.Minute),
		CreatedAt:           now,
		UpdatedAt:           now,
	})

	uc := NewInitDurableUploadUseCase(newFakeDurableUploadTxRunner(store), &fakeDurableUploadProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	}, DurableUploadConfig{
		Now:                func() time.Time { return now },
		BuildObjectKey:     deterministicObjectKeyBuilder,
		UploadURLExpiry:    5 * time.Minute,
		IntentTTL:          10 * time.Minute,
		UploadGraceWindow:  30 * time.Minute,
		MaxObjectKeyTrials: 3,
	})

	result, err := uc.Execute(context.Background(), InitDurableUploadInput{
		Binding:             binding,
		Kind:                AssetKindImage,
		DeclaredContentType: "image/webp",
		Metadata:            []byte(`{"source":"camera"}`),
		IdempotencyKey:      "idem-mismatch",
	})
	if !errors.Is(err, ErrAssetUploadIdempotencyConflict) {
		t.Fatalf("expected ErrAssetUploadIdempotencyConflict, got result=%+v err=%v", result, err)
	}
}

func TestCompleteDurableUploadCreatesReferenceAtomically(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeDataset,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
	store.putResolvedOwner(binding)
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindImage,
		Status:         AssetStatusPendingUpload,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/complete",
		ContentType:    "image/png",
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedAt:      now,
		UpdatedAt:      now,
	})
	store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "image/png",
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      "idem-complete",
		ExpiresAt:           now.Add(10 * time.Minute),
		CreatedAt:           now,
		UpdatedAt:           now,
	})
	provider := &fakeDurableUploadProvider{
		bucket: "assets",
		stat: &storage.ObjectStat{
			Size:        256,
			ContentType: "image/webp",
		},
	}
	size := int64(256)
	sha := "abc123"

	uc := NewCompleteDurableUploadUseCase(newFakeDurableUploadTxRunner(store), provider, DurableUploadConfig{
		Now: func() time.Time { return now },
	})

	result, err := uc.Execute(context.Background(), CompleteDurableUploadInput{
		AssetID:          asset.ID,
		RequestSizeBytes: &size,
		SHA256Hex:        &sha,
	})
	if err != nil {
		t.Fatalf("complete durable upload: %v", err)
	}
	if result == nil || result.Asset == nil || result.Intent == nil || result.Reference == nil {
		t.Fatalf("unexpected complete result: %+v", result)
	}
	if result.Asset.Status != AssetStatusReady {
		t.Fatalf("asset status got %q want %q", result.Asset.Status, AssetStatusReady)
	}
	if result.Asset.SizeBytes != 256 {
		t.Fatalf("asset size got %d want %d", result.Asset.SizeBytes, 256)
	}
	if result.Asset.ContentType != "image/webp" {
		t.Fatalf("asset content type got %q want %q", result.Asset.ContentType, "image/webp")
	}
	if result.Intent.State != AssetUploadIntentStateCompleted {
		t.Fatalf("intent state got %q want %q", result.Intent.State, AssetUploadIntentStateCompleted)
	}
	if result.Reference.Binding != binding {
		t.Fatalf("reference binding got %+v want %+v", result.Reference.Binding, binding)
	}
}

func TestCompleteDurableUploadReplaysCompletedIntent(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeSample,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRolePrimary,
		IsPrimary: true,
	}
	store.putResolvedOwner(binding)
	readyAt := now.Add(-time.Minute)
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindImage,
		Status:         AssetStatusReady,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/ready",
		ContentType:    "image/png",
		SizeBytes:      512,
		ReadyAt:        &readyAt,
		CreatedAt:      now.Add(-10 * time.Minute),
		UpdatedAt:      readyAt,
	})
	completedAt := readyAt
	store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "image/png",
		State:               AssetUploadIntentStateCompleted,
		IdempotencyKey:      "idem-done",
		ExpiresAt:           now.Add(10 * time.Minute),
		CompletedAt:         &completedAt,
		CreatedAt:           now.Add(-10 * time.Minute),
		UpdatedAt:           completedAt,
	})
	store.putReference(AssetReference{
		ID:        uuid.New(),
		AssetID:   asset.ID,
		Binding:   binding,
		Lifecycle: AssetReferenceLifecycleDurable,
		CreatedAt: completedAt,
	})

	uc := NewCompleteDurableUploadUseCase(newFakeDurableUploadTxRunner(store), &fakeDurableUploadProvider{
		bucket: "assets",
	}, DurableUploadConfig{
		Now: func() time.Time { return now },
	})

	result, err := uc.Execute(context.Background(), CompleteDurableUploadInput{
		AssetID: asset.ID,
	})
	if err != nil {
		t.Fatalf("replay complete durable upload: %v", err)
	}
	if result.Reference == nil || result.Reference.AssetID != asset.ID {
		t.Fatalf("unexpected replay reference: %+v", result.Reference)
	}
	if got, want := len(store.references), 1; got != want {
		t.Fatalf("reference count got %d want %d", got, want)
	}
}

func TestCompleteDurableUploadRejectsExpiredIntent(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeDataset,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
	store.putResolvedOwner(binding)
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindArchive,
		Status:         AssetStatusPendingUpload,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "archive/stale",
		ContentType:    "application/zip",
		CreatedAt:      now.Add(-15 * time.Minute),
		UpdatedAt:      now.Add(-15 * time.Minute),
	})
	store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "application/zip",
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      "idem-expired",
		ExpiresAt:           now.Add(-time.Minute),
		CreatedAt:           now.Add(-15 * time.Minute),
		UpdatedAt:           now.Add(-15 * time.Minute),
	})

	uc := NewCompleteDurableUploadUseCase(newFakeDurableUploadTxRunner(store), &fakeDurableUploadProvider{
		bucket: "assets",
		stat: &storage.ObjectStat{
			Size:        10,
			ContentType: "application/zip",
		},
	}, DurableUploadConfig{
		Now: func() time.Time { return now },
	})

	result, err := uc.Execute(context.Background(), CompleteDurableUploadInput{
		AssetID: asset.ID,
	})
	if !errors.Is(err, ErrAssetUploadIntentExpired) {
		t.Fatalf("expected ErrAssetUploadIntentExpired, got result=%+v err=%v", result, err)
	}
	storedIntent := store.mustGetIntent(asset.ID)
	if storedIntent.State != AssetUploadIntentStateExpired {
		t.Fatalf("intent state got %q want %q", storedIntent.State, AssetUploadIntentStateExpired)
	}
	storedAsset := store.mustGetAsset(asset.ID)
	if storedAsset.Status != AssetStatusPendingUpload {
		t.Fatalf("asset status got %q want %q", storedAsset.Status, AssetStatusPendingUpload)
	}
}

func TestCompleteDurableUploadFailsOnPrimaryConflict(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeSample,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRolePrimary,
		IsPrimary: true,
	}
	store.putResolvedOwner(binding)
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindImage,
		Status:         AssetStatusPendingUpload,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/primary",
		ContentType:    "image/png",
		CreatedAt:      now,
		UpdatedAt:      now,
	})
	store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "image/png",
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      "idem-primary",
		ExpiresAt:           now.Add(10 * time.Minute),
		CreatedAt:           now,
		UpdatedAt:           now,
	})
	store.putReference(AssetReference{
		ID:      uuid.New(),
		AssetID: uuid.New(),
		Binding: DurableOwnerBinding{
			OwnerType: AssetOwnerTypeSample,
			OwnerID:   binding.OwnerID,
			Role:      AssetReferenceRolePrimary,
			IsPrimary: true,
		},
		Lifecycle: AssetReferenceLifecycleDurable,
		CreatedAt: now.Add(-time.Minute),
	})
	provider := &fakeDurableUploadProvider{
		bucket: "assets",
		stat: &storage.ObjectStat{
			Size:        64,
			ContentType: "image/png",
		},
	}

	uc := NewCompleteDurableUploadUseCase(newFakeDurableUploadTxRunner(store), provider, DurableUploadConfig{
		Now: func() time.Time { return now },
	})

	result, err := uc.Execute(context.Background(), CompleteDurableUploadInput{
		AssetID: asset.ID,
	})
	if !errors.Is(err, ErrDurableReferenceConflict) {
		t.Fatalf("expected ErrDurableReferenceConflict, got result=%+v err=%v", result, err)
	}
	storedAsset := store.mustGetAsset(asset.ID)
	if storedAsset.Status != AssetStatusPendingUpload {
		t.Fatalf("asset status got %q want %q", storedAsset.Status, AssetStatusPendingUpload)
	}
	storedIntent := store.mustGetIntent(asset.ID)
	if storedIntent.State != AssetUploadIntentStateInitiated {
		t.Fatalf("intent state got %q want %q", storedIntent.State, AssetUploadIntentStateInitiated)
	}
}

func TestCancelDurableUploadMarksIntentCanceled(t *testing.T) {
	now := time.Date(2026, 3, 18, 12, 0, 0, 0, time.UTC)
	store := newFakeDurableUploadTxStore()
	binding := DurableOwnerBinding{
		OwnerType: AssetOwnerTypeProject,
		OwnerID:   uuid.New(),
		Role:      AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
	asset := store.putAsset(Asset{
		ID:             uuid.New(),
		Kind:           AssetKindDocument,
		Status:         AssetStatusPendingUpload,
		StorageBackend: AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "document/cancel",
		ContentType:    "application/pdf",
		CreatedAt:      now,
		UpdatedAt:      now,
	})
	store.putIntent(AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             asset.ID,
		Binding:             binding,
		DeclaredContentType: "application/pdf",
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      "idem-cancel",
		ExpiresAt:           now.Add(10 * time.Minute),
		CreatedAt:           now,
		UpdatedAt:           now,
	})

	uc := NewCancelDurableUploadUseCase(newFakeDurableUploadTxRunner(store), DurableUploadConfig{
		Now: func() time.Time { return now },
	})

	result, err := uc.Execute(context.Background(), asset.ID)
	if err != nil {
		t.Fatalf("cancel durable upload: %v", err)
	}
	if result == nil || result.Intent == nil {
		t.Fatalf("unexpected cancel result: %+v", result)
	}
	if result.Intent.State != AssetUploadIntentStateCanceled {
		t.Fatalf("intent state got %q want %q", result.Intent.State, AssetUploadIntentStateCanceled)
	}
	if store.mustGetAsset(asset.ID).Status != AssetStatusPendingUpload {
		t.Fatalf("cancel should not delete or finalize asset")
	}
	if got, want := len(store.references), 0; got != want {
		t.Fatalf("reference count got %d want %d", got, want)
	}
}

func deterministicObjectKeyBuilder(kind AssetKind, attempt int) string {
	return string(kind) + "/object-" + string(rune('0'+attempt))
}

type fakeDurableUploadProvider struct {
	bucket             string
	putURL             string
	stat               *storage.ObjectStat
	statErr            error
	lastPutObjectKey   string
	lastPutContentType string
	lastStatObjectKey  string
}

func (p *fakeDurableUploadProvider) Bucket() string { return p.bucket }

func (p *fakeDurableUploadProvider) SignPutObject(_ context.Context, objectKey string, _ time.Duration, contentType string) (string, error) {
	p.lastPutObjectKey = objectKey
	p.lastPutContentType = contentType
	return p.putURL, nil
}

func (p *fakeDurableUploadProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", nil
}

func (p *fakeDurableUploadProvider) StatObject(_ context.Context, objectKey string) (*storage.ObjectStat, error) {
	p.lastStatObjectKey = objectKey
	if p.statErr != nil {
		return nil, p.statErr
	}
	return p.stat, nil
}

func (p *fakeDurableUploadProvider) DownloadObject(context.Context, string, string) error {
	return nil
}

type fakeDurableUploadTxRunner struct {
	store *fakeDurableUploadTxStore
}

func newFakeDurableUploadTxRunner(store *fakeDurableUploadTxStore) *fakeDurableUploadTxRunner {
	return &fakeDurableUploadTxRunner{store: store}
}

func (r *fakeDurableUploadTxRunner) InTx(ctx context.Context, fn func(store DurableUploadTxStore) error) error {
	working := r.store.clone()
	if err := fn(working); err != nil {
		return err
	}
	r.store.replaceWith(working)
	return nil
}

type fakeDurableUploadTxStore struct {
	assets         map[uuid.UUID]Asset
	intents        map[uuid.UUID]AssetUploadIntent
	references     map[uuid.UUID]AssetReference
	resolvedOwners map[string]ResolvedOwner
}

func newFakeDurableUploadTxStore() *fakeDurableUploadTxStore {
	return &fakeDurableUploadTxStore{
		assets:         make(map[uuid.UUID]Asset),
		intents:        make(map[uuid.UUID]AssetUploadIntent),
		references:     make(map[uuid.UUID]AssetReference),
		resolvedOwners: make(map[string]ResolvedOwner),
	}
}

func (s *fakeDurableUploadTxStore) ResolveOwner(_ context.Context, ownerType AssetOwnerType, ownerID uuid.UUID) (*ResolvedOwner, error) {
	key := ownerKey(ownerType, ownerID)
	resolved, ok := s.resolvedOwners[key]
	if !ok {
		return nil, nil
	}
	copy := resolved
	if resolved.DatasetID != nil {
		datasetID := *resolved.DatasetID
		copy.DatasetID = &datasetID
	}
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) CreatePendingAsset(_ context.Context, params CreatePendingAssetParams) (*Asset, error) {
	asset := Asset{
		ID:             uuid.New(),
		Kind:           params.Kind,
		Status:         AssetStatusPendingUpload,
		StorageBackend: params.StorageBackend,
		Bucket:         params.Bucket,
		ObjectKey:      params.BuildObjectKey(0),
		ContentType:    params.ContentType,
		Metadata:       append([]byte(nil), params.Metadata...),
		CreatedBy:      cloneUUIDPtr(params.CreatedBy),
		CreatedAt:      time.Now().UTC(),
		UpdatedAt:      time.Now().UTC(),
	}
	s.assets[asset.ID] = asset
	copy := asset
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) GetAsset(_ context.Context, id uuid.UUID) (*Asset, error) {
	asset, ok := s.assets[id]
	if !ok {
		return nil, nil
	}
	copy := cloneAsset(asset)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) MarkAssetReady(_ context.Context, params MarkAssetReadyInput) (*Asset, error) {
	asset, ok := s.assets[params.ID]
	if !ok {
		return nil, nil
	}
	asset.Status = AssetStatusReady
	asset.SizeBytes = params.SizeBytes
	asset.Sha256Hex = cloneStringPtr(params.SHA256Hex)
	asset.ContentType = params.ContentType
	asset.ReadyAt = cloneTimePtr(params.ReadyAt)
	asset.UpdatedAt = params.UpdatedAt
	s.assets[asset.ID] = asset
	copy := cloneAsset(asset)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) GetUploadIntentByAssetID(_ context.Context, assetID uuid.UUID) (*AssetUploadIntent, error) {
	intent, ok := s.intents[assetID]
	if !ok {
		return nil, nil
	}
	copy := cloneIntent(intent)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) GetUploadIntentByOwnerKey(_ context.Context, params GetAssetUploadIntentByOwnerKeyInput) (*AssetUploadIntent, error) {
	for _, intent := range s.intents {
		if intent.Binding.OwnerType == params.OwnerType &&
			intent.Binding.OwnerID == params.OwnerID &&
			intent.Binding.Role == params.Role &&
			intent.IdempotencyKey == params.IdempotencyKey {
			copy := cloneIntent(intent)
			return &copy, nil
		}
	}
	return nil, nil
}

func (s *fakeDurableUploadTxStore) CreateUploadIntent(_ context.Context, params CreateAssetUploadIntentInput) (*AssetUploadIntent, error) {
	intent := AssetUploadIntent{
		ID:                  uuid.New(),
		AssetID:             params.AssetID,
		Binding:             params.Binding,
		DeclaredContentType: params.DeclaredContentType,
		State:               AssetUploadIntentStateInitiated,
		IdempotencyKey:      params.IdempotencyKey,
		ExpiresAt:           params.ExpiresAt,
		CreatedBy:           cloneUUIDPtr(params.CreatedBy),
		CreatedAt:           params.CreatedAt,
		UpdatedAt:           params.CreatedAt,
	}
	s.intents[intent.AssetID] = intent
	copy := cloneIntent(intent)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) MarkUploadIntentCompleted(_ context.Context, params MarkAssetUploadIntentCompletedInput) (*AssetUploadIntent, error) {
	intent, ok := s.intents[params.AssetID]
	if !ok {
		return nil, nil
	}
	intent.State = AssetUploadIntentStateCompleted
	intent.CompletedAt = cloneTimePtr(&params.CompletedAt)
	intent.UpdatedAt = params.CompletedAt
	s.intents[intent.AssetID] = intent
	copy := cloneIntent(intent)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) MarkUploadIntentCanceled(_ context.Context, params MarkAssetUploadIntentCanceledInput) (*AssetUploadIntent, error) {
	intent, ok := s.intents[params.AssetID]
	if !ok {
		return nil, nil
	}
	intent.State = AssetUploadIntentStateCanceled
	intent.CanceledAt = cloneTimePtr(&params.CanceledAt)
	intent.UpdatedAt = params.CanceledAt
	s.intents[intent.AssetID] = intent
	copy := cloneIntent(intent)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) MarkUploadIntentExpired(_ context.Context, params MarkAssetUploadIntentExpiredInput) (*AssetUploadIntent, error) {
	intent, ok := s.intents[params.AssetID]
	if !ok {
		return nil, nil
	}
	intent.State = AssetUploadIntentStateExpired
	intent.UpdatedAt = params.ExpiredAt
	s.intents[intent.AssetID] = intent
	copy := cloneIntent(intent)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) CreateDurableReference(_ context.Context, params CreateAssetReferenceInput) (*AssetReference, error) {
	for _, ref := range s.references {
		if ref.DeletedAt != nil {
			continue
		}
		if ref.AssetID == params.AssetID &&
			ref.Binding.OwnerType == params.Binding.OwnerType &&
			ref.Binding.OwnerID == params.Binding.OwnerID &&
			ref.Binding.Role == params.Binding.Role {
			return nil, &pgconn.PgError{Code: "23505", ConstraintName: "asset_reference_active_asset_owner_role_key"}
		}
		if params.Binding.IsPrimary &&
			ref.Binding.IsPrimary &&
			ref.Binding.OwnerType == params.Binding.OwnerType &&
			ref.Binding.OwnerID == params.Binding.OwnerID &&
			ref.Binding.Role == params.Binding.Role {
			return nil, &pgconn.PgError{Code: "23505", ConstraintName: "asset_reference_active_owner_role_primary_key"}
		}
	}

	reference := AssetReference{
		ID:        uuid.New(),
		AssetID:   params.AssetID,
		Binding:   params.Binding,
		Lifecycle: params.Lifecycle,
		Metadata:  append([]byte(nil), params.Metadata...),
		CreatedBy: cloneUUIDPtr(params.CreatedBy),
		CreatedAt: params.CreatedAt,
	}
	s.references[reference.ID] = reference
	copy := cloneReference(reference)
	return &copy, nil
}

func (s *fakeDurableUploadTxStore) ListActiveReferencesByOwner(_ context.Context, params ListActiveReferencesByOwnerInput) ([]AssetReference, error) {
	var refs []AssetReference
	for _, ref := range s.references {
		if ref.DeletedAt != nil {
			continue
		}
		if ref.Binding.OwnerType == params.OwnerType && ref.Binding.OwnerID == params.OwnerID {
			refs = append(refs, cloneReference(ref))
		}
	}
	return refs, nil
}

func (s *fakeDurableUploadTxStore) clone() *fakeDurableUploadTxStore {
	cloned := newFakeDurableUploadTxStore()
	for id, asset := range s.assets {
		cloned.assets[id] = cloneAsset(asset)
	}
	for id, intent := range s.intents {
		cloned.intents[id] = cloneIntent(intent)
	}
	for id, ref := range s.references {
		cloned.references[id] = cloneReference(ref)
	}
	for key, owner := range s.resolvedOwners {
		copy := owner
		if owner.DatasetID != nil {
			datasetID := *owner.DatasetID
			copy.DatasetID = &datasetID
		}
		cloned.resolvedOwners[key] = copy
	}
	return cloned
}

func (s *fakeDurableUploadTxStore) replaceWith(other *fakeDurableUploadTxStore) {
	*s = *other.clone()
}

func (s *fakeDurableUploadTxStore) putResolvedOwner(binding DurableOwnerBinding) {
	s.resolvedOwners[ownerKey(binding.OwnerType, binding.OwnerID)] = ResolvedOwner{
		OwnerType: binding.OwnerType,
		OwnerID:   binding.OwnerID,
	}
}

func (s *fakeDurableUploadTxStore) putAsset(asset Asset) *Asset {
	s.assets[asset.ID] = cloneAsset(asset)
	copy := cloneAsset(asset)
	return &copy
}

func (s *fakeDurableUploadTxStore) putIntent(intent AssetUploadIntent) *AssetUploadIntent {
	s.intents[intent.AssetID] = cloneIntent(intent)
	copy := cloneIntent(intent)
	return &copy
}

func (s *fakeDurableUploadTxStore) putReference(reference AssetReference) *AssetReference {
	s.references[reference.ID] = cloneReference(reference)
	copy := cloneReference(reference)
	return &copy
}

func (s *fakeDurableUploadTxStore) mustGetAsset(id uuid.UUID) Asset {
	asset, ok := s.assets[id]
	if !ok {
		panic("missing asset")
	}
	return cloneAsset(asset)
}

func (s *fakeDurableUploadTxStore) mustGetIntent(assetID uuid.UUID) AssetUploadIntent {
	intent, ok := s.intents[assetID]
	if !ok {
		panic("missing intent")
	}
	return cloneIntent(intent)
}

func ownerKey(ownerType AssetOwnerType, ownerID uuid.UUID) string {
	return string(ownerType) + ":" + ownerID.String()
}

func cloneAsset(asset Asset) Asset {
	asset.Sha256Hex = cloneStringPtr(asset.Sha256Hex)
	asset.Metadata = cloneBytes(asset.Metadata)
	asset.CreatedBy = cloneUUIDPtr(asset.CreatedBy)
	asset.ReadyAt = cloneTimePtr(asset.ReadyAt)
	asset.OrphanedAt = cloneTimePtr(asset.OrphanedAt)
	return asset
}

func cloneIntent(intent AssetUploadIntent) AssetUploadIntent {
	intent.CreatedBy = cloneUUIDPtr(intent.CreatedBy)
	intent.CompletedAt = cloneTimePtr(intent.CompletedAt)
	intent.CanceledAt = cloneTimePtr(intent.CanceledAt)
	return intent
}

func cloneReference(reference AssetReference) AssetReference {
	reference.Metadata = cloneBytes(reference.Metadata)
	reference.CreatedBy = cloneUUIDPtr(reference.CreatedBy)
	reference.DeletedAt = cloneTimePtr(reference.DeletedAt)
	return reference
}
