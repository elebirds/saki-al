package apihttp_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	assetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/apihttp"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/google/uuid"
)

func TestInitAssetUploadReturnsPendingAssetAndSignedPutURL(t *testing.T) {
	userID := uuid.New()
	ownerID := uuid.New()
	assetID := uuid.New()
	module := newFakeAssetModule()
	module.initUpload.result = &assetapp.InitDurableUploadResult{
		Asset: &assetapp.Asset{
			ID:             assetID,
			Kind:           assetapp.AssetKindImage,
			Status:         assetapp.AssetStatusPendingUpload,
			StorageBackend: assetapp.AssetStorageBackendMinio,
			Bucket:         "assets",
			ObjectKey:      "image/demo-object",
			ContentType:    "image/png",
			Metadata:       []byte(`{"source":"camera"}`),
		},
		Intent: &assetapp.AssetUploadIntent{
			AssetID: assetID,
			State:   assetapp.AssetUploadIntentStateInitiated,
		},
		UploadTicket: &assetapp.Ticket{
			AssetID: assetID,
			URL:     "https://object.test/upload",
		},
	}

	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(durableInitRequest(ownerID, "image")))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("unexpected init status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body struct {
		Asset struct {
			ID             string         `json:"id"`
			Status         string         `json:"status"`
			StorageBackend string         `json:"storage_backend"`
			Bucket         string         `json:"bucket"`
			ObjectKey      string         `json:"object_key"`
			Metadata       map[string]any `json:"metadata"`
		} `json:"asset"`
		IntentState string `json:"intent_state"`
		UploadURL   string `json:"upload_url"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode init response: %v", err)
	}
	if body.Asset.ID != assetID.String() || body.Asset.Status != string(assetapp.AssetStatusPendingUpload) {
		t.Fatalf("unexpected init asset: %+v", body.Asset)
	}
	if body.IntentState != string(assetapp.AssetUploadIntentStateInitiated) {
		t.Fatalf("unexpected init intent state: %+v", body)
	}
	if body.UploadURL != "https://object.test/upload" || body.ExpiresIn <= 0 {
		t.Fatalf("unexpected init response: %+v", body)
	}
	if got, want := module.initUpload.calls, 1; got != want {
		t.Fatalf("init usecase calls got %d want %d", got, want)
	}
	if got := module.initUpload.lastInput.CreatedBy; got == nil || *got != userID {
		t.Fatalf("unexpected created_by: %+v", got)
	}
	if got, want := module.initUpload.lastInput.Binding.OwnerType, assetapp.AssetOwnerTypeDataset; got != want {
		t.Fatalf("owner type got %q want %q", got, want)
	}
	if got, want := module.initUpload.lastInput.Binding.OwnerID, ownerID; got != want {
		t.Fatalf("owner id got %s want %s", got, want)
	}
	if got, want := module.initUpload.lastInput.Binding.Role, assetapp.AssetReferenceRoleAttachment; got != want {
		t.Fatalf("role got %q want %q", got, want)
	}
	if module.initUpload.lastInput.Binding.IsPrimary {
		t.Fatalf("expected is_primary to be false")
	}
	if got, want := module.initUpload.lastInput.Kind, assetapp.AssetKindImage; got != want {
		t.Fatalf("kind got %q want %q", got, want)
	}
	if got, want := module.initUpload.lastInput.DeclaredContentType, "image/png"; got != want {
		t.Fatalf("content type got %q want %q", got, want)
	}
	if got, want := module.initUpload.lastInput.IdempotencyKey, "idem-init-1"; got != want {
		t.Fatalf("idempotency key got %q want %q", got, want)
	}
	var metadata map[string]any
	if err := json.Unmarshal(module.initUpload.lastInput.Metadata, &metadata); err != nil {
		t.Fatalf("decode forwarded metadata: %v", err)
	}
	if metadata["source"] != "camera" {
		t.Fatalf("unexpected forwarded metadata: %+v", metadata)
	}
}

func TestInitAssetUploadAllowsNonUUIDUserID(t *testing.T) {
	ownerID := uuid.New()
	module := newFakeAssetModule()
	module.initUpload.result = &assetapp.InitDurableUploadResult{
		Asset: &assetapp.Asset{
			ID:             uuid.New(),
			Kind:           assetapp.AssetKindImage,
			Status:         assetapp.AssetStatusPendingUpload,
			StorageBackend: assetapp.AssetStorageBackendMinio,
			Bucket:         "assets",
			ObjectKey:      "image/demo-object",
			ContentType:    "image/png",
			Metadata:       []byte(`{}`),
		},
		Intent: &assetapp.AssetUploadIntent{
			State: assetapp.AssetUploadIntentStateInitiated,
		},
		UploadTicket: &assetapp.Ticket{
			URL: "https://object.test/upload",
		},
	}

	handler, token := newAssetHTTPHandlerWithSubjectKey(t, "user-plain-text", module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(durableInitRequest(ownerID, "image")))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("unexpected init status: %d body=%s", rec.Code, rec.Body.String())
	}
	if module.initUpload.lastInput.CreatedBy != nil {
		t.Fatalf("expected created_by to be nil for non-uuid user id, got %+v", module.initUpload.lastInput.CreatedBy)
	}
}

func TestInitAssetUploadRequiresOwnerBindingAndIdempotencyKey(t *testing.T) {
	userID := uuid.New()
	module := newFakeAssetModule()
	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(`{"kind":"image","content_type":"image/png","metadata":{}}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected missing owner binding to be rejected, got status=%d body=%s", rec.Code, rec.Body.String())
	}
	if module.initUpload.calls != 0 {
		t.Fatalf("expected init usecase not to run, got calls=%d", module.initUpload.calls)
	}
}

func TestInitAssetUploadRejectsUnknownFields(t *testing.T) {
	userID := uuid.New()
	module := newFakeAssetModule()
	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	reqBody := fmt.Sprintf(`{"owner_type":"dataset","owner_id":"%s","role":"attachment","is_primary":false,"idempotency_key":"idem-init-1","kind":"image","content_type":"image/png","metadata":{},"unexpected":true}`, uuid.New())
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(reqBody))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code == http.StatusCreated {
		t.Fatalf("expected unknown init field to be rejected, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestInitAssetUploadRejectsUnsupportedKind(t *testing.T) {
	userID := uuid.New()
	module := newFakeAssetModule()
	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(durableInitRequest(uuid.New(), "runtime-task")))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid kind to be rejected, got status=%d body=%s", rec.Code, rec.Body.String())
	}
	if module.initUpload.calls != 0 {
		t.Fatalf("expected init usecase not to run, got calls=%d", module.initUpload.calls)
	}
}

func TestInitAssetUploadReplaysCompletedIntentWithoutUploadURL(t *testing.T) {
	userID := uuid.New()
	ownerID := uuid.New()
	assetID := uuid.New()
	module := newFakeAssetModule()
	module.initUpload.result = &assetapp.InitDurableUploadResult{
		Asset: &assetapp.Asset{
			ID:             assetID,
			Kind:           assetapp.AssetKindImage,
			Status:         assetapp.AssetStatusReady,
			StorageBackend: assetapp.AssetStorageBackendMinio,
			Bucket:         "assets",
			ObjectKey:      "image/finalized-object",
			ContentType:    "image/webp",
			SizeBytes:      256,
			Metadata:       []byte(`{"source":"camera"}`),
		},
		Intent: &assetapp.AssetUploadIntent{
			AssetID: assetID,
			State:   assetapp.AssetUploadIntentStateCompleted,
		},
	}

	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(durableInitRequest(ownerID, "image")))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("unexpected completed replay status: %d body=%s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode replay response: %v", err)
	}
	if body["intent_state"] != string(assetapp.AssetUploadIntentStateCompleted) {
		t.Fatalf("unexpected replay response: %+v", body)
	}
	if value, ok := body["upload_url"]; ok && value != nil {
		t.Fatalf("completed replay should not return upload_url: %+v", body)
	}
	if value, ok := body["expires_in"]; ok && value != nil {
		t.Fatalf("completed replay should not return expires_in: %+v", body)
	}
}

func TestCompleteAssetUploadUsesDurableUseCase(t *testing.T) {
	userID := uuid.New()
	assetID := uuid.New()
	size := int64(20)
	sha := "abc123"
	module := newFakeAssetModule()
	module.completeUpload.result = &assetapp.CompleteDurableUploadResult{
		Asset: &assetapp.Asset{
			ID:             assetID,
			Kind:           assetapp.AssetKindImage,
			Status:         assetapp.AssetStatusReady,
			StorageBackend: assetapp.AssetStorageBackendMinio,
			Bucket:         "assets",
			ObjectKey:      "image/demo-object",
			ContentType:    "image/webp",
			SizeBytes:      20,
		},
		Intent: &assetapp.AssetUploadIntent{
			AssetID: assetID,
			State:   assetapp.AssetUploadIntentStateCompleted,
		},
	}
	module.intentStore.items[assetID] = assetapp.AssetUploadIntent{
		AssetID: assetID,
		Binding: durableDatasetBinding(uuid.New()),
	}

	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/"+assetID.String()+":complete", bytes.NewBufferString(`{"size_bytes":20,"sha256_hex":"abc123"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected complete status: %d body=%s", rec.Code, rec.Body.String())
	}
	if got, want := module.completeUpload.calls, 1; got != want {
		t.Fatalf("complete usecase calls got %d want %d", got, want)
	}
	if got, want := module.completeUpload.lastInput.AssetID, assetID; got != want {
		t.Fatalf("complete asset id got %s want %s", got, want)
	}
	if module.completeUpload.lastInput.RequestSizeBytes == nil || *module.completeUpload.lastInput.RequestSizeBytes != size {
		t.Fatalf("unexpected complete size input: %+v", module.completeUpload.lastInput.RequestSizeBytes)
	}
	if module.completeUpload.lastInput.SHA256Hex == nil || *module.completeUpload.lastInput.SHA256Hex != sha {
		t.Fatalf("unexpected complete sha input: %+v", module.completeUpload.lastInput.SHA256Hex)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode complete response: %v", err)
	}
	if body["id"] != assetID.String() || body["status"] != string(assetapp.AssetStatusReady) {
		t.Fatalf("unexpected complete response: %+v", body)
	}
}

func TestCompleteAssetUploadRejectsUnknownFields(t *testing.T) {
	userID := uuid.New()
	module := newFakeAssetModule()

	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/"+uuid.New().String()+":complete", bytes.NewBufferString(`{"size_bytes":20,"unknown":"x"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code == http.StatusOK {
		t.Fatalf("expected unknown complete field to be rejected, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestCancelAssetUploadCancelsInitiatedIntent(t *testing.T) {
	userID := uuid.New()
	assetID := uuid.New()
	module := newFakeAssetModule()
	module.cancelUpload.result = &assetapp.CancelDurableUploadResult{
		Intent: &assetapp.AssetUploadIntent{
			AssetID: assetID,
			State:   assetapp.AssetUploadIntentStateCanceled,
		},
	}
	module.intentStore.items[assetID] = assetapp.AssetUploadIntent{
		AssetID: assetID,
		Binding: durableDatasetBinding(uuid.New()),
	}

	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodPost, "/assets/"+assetID.String()+":cancel", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected cancel status: %d body=%s", rec.Code, rec.Body.String())
	}
	if got, want := module.cancelUpload.calls, 1; got != want {
		t.Fatalf("cancel usecase calls got %d want %d", got, want)
	}
	if got, want := module.cancelUpload.lastAssetID, assetID; got != want {
		t.Fatalf("cancel asset id got %s want %s", got, want)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode cancel response: %v", err)
	}
	if body["asset_id"] != assetID.String() || body["intent_state"] != string(assetapp.AssetUploadIntentStateCanceled) {
		t.Fatalf("unexpected cancel body: %+v", body)
	}
}

func TestGetAssetReturnsMetadata(t *testing.T) {
	userID := uuid.New()
	assetID := uuid.New()
	module := newFakeAssetModule()
	module.assets.items[assetID] = assetapp.Asset{
		ID:             assetID,
		Kind:           assetapp.AssetKindImage,
		Status:         assetapp.AssetStatusReady,
		StorageBackend: assetapp.AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/demo-object",
		ContentType:    "image/png",
		SizeBytes:      20,
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedBy:      &userID,
	}

	handler, token := newAssetHTTPHandler(t, userID, module, &fakeProvider{bucket: "assets"})
	req := httptest.NewRequest(http.MethodGet, "/assets/"+assetID.String(), nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected get status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode get response: %v", err)
	}
	if body["id"] != assetID.String() || body["status"] != string(assetapp.AssetStatusReady) {
		t.Fatalf("unexpected get body: %+v", body)
	}
	metadata, ok := body["metadata"].(map[string]any)
	if !ok || metadata["source"] != "camera" {
		t.Fatalf("unexpected metadata body: %+v", body)
	}
	if _, ok := body["download_url"]; ok {
		t.Fatalf("get asset should not return download url: %+v", body)
	}
}

func TestSignAssetDownloadReturnsSignedGetURL(t *testing.T) {
	userID := uuid.New()
	assetID := uuid.New()
	module := newFakeAssetModule()
	module.assets.items[assetID] = assetapp.Asset{
		ID:             assetID,
		Kind:           assetapp.AssetKindImage,
		Status:         assetapp.AssetStatusReady,
		StorageBackend: assetapp.AssetStorageBackendMinio,
		Bucket:         "assets",
		ObjectKey:      "image/demo-object",
		ContentType:    "image/png",
	}
	provider := &fakeProvider{
		bucket: "assets",
		getURL: "https://object.test/download",
	}

	handler, token := newAssetHTTPHandler(t, userID, module, provider)
	req := httptest.NewRequest(http.MethodPost, "/assets/"+assetID.String()+":sign-download", bytes.NewBufferString(`{}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected sign-download status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode sign-download response: %v", err)
	}
	if body["asset_id"] != assetID.String() || body["download_url"] != provider.getURL {
		t.Fatalf("unexpected sign-download body: %+v", body)
	}
	if expiresIn, ok := body["expires_in"].(float64); !ok || expiresIn <= 0 {
		t.Fatalf("unexpected sign-download body: %+v", body)
	}
}

func newAssetHTTPHandler(t *testing.T, userID uuid.UUID, module *fakeAssetModule, provider *fakeProvider) (http.Handler, string) {
	t.Helper()

	return newAssetHTTPHandlerWithSubjectKey(t, userID.String(), module, provider)
}

func newAssetHTTPHandlerWithSubjectKey(t *testing.T, subjectKey string, module *fakeAssetModule, provider *fakeProvider) (http.Handler, string) {
	t.Helper()

	accessStore := newFakeAccessStore(subjectKey)
	authenticator := accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(accessStore)
	token, err := authenticator.IssueTokenContext(context.Background(), subjectKey)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}

	if module == nil {
		module = newFakeAssetModule()
	}
	if provider == nil {
		provider = &fakeProvider{bucket: "assets"}
	}

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       authenticator,
		AccessStore:         accessStore,
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
		Asset: assetapi.Dependencies{
			Store:           module.assets,
			IntentStore:     module.intentStore,
			InitUpload:      module.initUpload,
			CompleteUpload:  module.completeUpload,
			CancelUpload:    module.cancelUpload,
			Provider:        provider,
			UploadURLExpiry: 5 * time.Minute,
			DownloadExpiry:  5 * time.Minute,
		},
	})
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}
	return handler, token
}

func durableInitRequest(ownerID uuid.UUID, kind string) string {
	return fmt.Sprintf(`{"owner_type":"dataset","owner_id":"%s","role":"attachment","is_primary":false,"idempotency_key":"idem-init-1","kind":"%s","content_type":"image/png","metadata":{"source":"camera"}}`, ownerID, kind)
}

type fakeAssetModule struct {
	assets         *fakeAssetStore
	intentStore    *fakeIntentStore
	initUpload     *fakeInitUploadUseCase
	completeUpload *fakeCompleteUploadUseCase
	cancelUpload   *fakeCancelUploadUseCase
}

func newFakeAssetModule() *fakeAssetModule {
	return &fakeAssetModule{
		assets:         newFakeAssetStore(),
		intentStore:    newFakeIntentStore(),
		initUpload:     &fakeInitUploadUseCase{},
		completeUpload: &fakeCompleteUploadUseCase{},
		cancelUpload:   &fakeCancelUploadUseCase{},
	}
}

type fakeAssetStore struct {
	items  map[uuid.UUID]assetapp.Asset
	getErr error
}

func newFakeAssetStore() *fakeAssetStore {
	return &fakeAssetStore{items: make(map[uuid.UUID]assetapp.Asset)}
}

func (s *fakeAssetStore) Get(_ context.Context, id uuid.UUID) (*assetapp.Asset, error) {
	if s.getErr != nil {
		return nil, s.getErr
	}
	asset, ok := s.items[id]
	if !ok {
		return nil, nil
	}
	copy := asset
	if asset.Sha256Hex != nil {
		sha := *asset.Sha256Hex
		copy.Sha256Hex = &sha
	}
	if asset.CreatedBy != nil {
		createdBy := *asset.CreatedBy
		copy.CreatedBy = &createdBy
	}
	copy.Metadata = append([]byte(nil), asset.Metadata...)
	return &copy, nil
}

type fakeInitUploadUseCase struct {
	calls     int
	lastInput assetapp.InitDurableUploadInput
	result    *assetapp.InitDurableUploadResult
	err       error
}

func (u *fakeInitUploadUseCase) Execute(_ context.Context, input assetapp.InitDurableUploadInput) (*assetapp.InitDurableUploadResult, error) {
	u.calls++
	u.lastInput = input
	return u.result, u.err
}

type fakeCompleteUploadUseCase struct {
	calls     int
	lastInput assetapp.CompleteDurableUploadInput
	result    *assetapp.CompleteDurableUploadResult
	err       error
}

func (u *fakeCompleteUploadUseCase) Execute(_ context.Context, input assetapp.CompleteDurableUploadInput) (*assetapp.CompleteDurableUploadResult, error) {
	u.calls++
	u.lastInput = input
	return u.result, u.err
}

type fakeCancelUploadUseCase struct {
	calls       int
	lastAssetID uuid.UUID
	result      *assetapp.CancelDurableUploadResult
	err         error
}

func (u *fakeCancelUploadUseCase) Execute(_ context.Context, assetID uuid.UUID) (*assetapp.CancelDurableUploadResult, error) {
	u.calls++
	u.lastAssetID = assetID
	return u.result, u.err
}

type fakeIntentStore struct {
	items  map[uuid.UUID]assetapp.AssetUploadIntent
	getErr error
}

func newFakeIntentStore() *fakeIntentStore {
	return &fakeIntentStore{items: make(map[uuid.UUID]assetapp.AssetUploadIntent)}
}

func (s *fakeIntentStore) GetUploadIntentByAssetID(_ context.Context, assetID uuid.UUID) (*assetapp.AssetUploadIntent, error) {
	if s.getErr != nil {
		return nil, s.getErr
	}
	intent, ok := s.items[assetID]
	if !ok {
		return nil, nil
	}
	copy := intent
	if intent.CreatedBy != nil {
		createdBy := *intent.CreatedBy
		copy.CreatedBy = &createdBy
	}
	if intent.CompletedAt != nil {
		completedAt := *intent.CompletedAt
		copy.CompletedAt = &completedAt
	}
	if intent.CanceledAt != nil {
		canceledAt := *intent.CanceledAt
		copy.CanceledAt = &canceledAt
	}
	return &copy, nil
}

type fakeProvider struct {
	bucket            string
	putURL            string
	getURL            string
	stat              *storage.ObjectStat
	statErr           error
	lastStatObjectKey string
}

func (p *fakeProvider) Bucket() string { return p.bucket }

func (p *fakeProvider) SignPutObject(context.Context, string, time.Duration, string) (string, error) {
	return p.putURL, nil
}

func (p *fakeProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return p.getURL, nil
}

func (p *fakeProvider) StatObject(_ context.Context, objectKey string) (*storage.ObjectStat, error) {
	p.lastStatObjectKey = objectKey
	if p.statErr != nil {
		return nil, p.statErr
	}
	if p.stat == nil {
		return nil, errors.New("missing stat object")
	}
	return p.stat, nil
}

func (p *fakeProvider) DownloadObject(context.Context, string, string) error { return nil }

type fakeAccessStore struct {
	principal   *accessdomain.Principal
	permissions []string
}

func newFakeAccessStore(subjectKey string) *fakeAccessStore {
	return &fakeAccessStore{
		principal: &accessdomain.Principal{
			ID:          uuid.New(),
			SubjectType: "user",
			SubjectKey:  subjectKey,
			DisplayName: subjectKey,
			Status:      accessdomain.PrincipalStatusActive,
		},
		permissions: []string{"assets:read", "assets:write", "datasets:write", "projects:write"},
	}
}

func (s *fakeAccessStore) GetPrincipalByUserID(_ context.Context, userID string) (*accessdomain.Principal, error) {
	if s.principal != nil && s.principal.SubjectKey == userID {
		copy := *s.principal
		return &copy, nil
	}
	return nil, nil
}

func (s *fakeAccessStore) GetPrincipalByID(_ context.Context, principalID uuid.UUID) (*accessdomain.Principal, error) {
	if s.principal != nil && s.principal.ID == principalID {
		copy := *s.principal
		return &copy, nil
	}
	return nil, nil
}

func (s *fakeAccessStore) ListPermissions(_ context.Context, principalID uuid.UUID) ([]string, error) {
	if s.principal == nil || s.principal.ID != principalID {
		return nil, nil
	}
	return append([]string(nil), s.permissions...), nil
}

func (s *fakeAccessStore) UpsertBootstrapPrincipal(context.Context, accessapp.BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	return nil, errors.New("not implemented")
}

type fakeRuntimeTaskCanceler struct{}

func (fakeRuntimeTaskCanceler) Handle(context.Context, runtimecommands.CancelTaskCommand) (*runtimecommands.TaskRecord, error) {
	return &runtimecommands.TaskRecord{}, nil
}

type fakeAnnotationSampleStore struct{}

func (fakeAnnotationSampleStore) Get(context.Context, uuid.UUID) (*annotationrepo.Sample, error) {
	return nil, nil
}

type fakeAnnotationDatasetStore struct{}

func (fakeAnnotationDatasetStore) Get(context.Context, uuid.UUID) (*datasetrepo.Dataset, error) {
	return nil, nil
}

type fakeAnnotationStore struct{}

func (fakeAnnotationStore) Create(context.Context, annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error) {
	return nil, nil
}

func (fakeAnnotationStore) ListByProjectSample(context.Context, uuid.UUID, uuid.UUID) ([]annotationrepo.Annotation, error) {
	return nil, nil
}

func durableDatasetBinding(ownerID uuid.UUID) assetapp.DurableOwnerBinding {
	return assetapp.DurableOwnerBinding{
		OwnerType: assetapp.AssetOwnerTypeDataset,
		OwnerID:   ownerID,
		Role:      assetapp.AssetReferenceRoleAttachment,
		IsPrimary: false,
	}
}
