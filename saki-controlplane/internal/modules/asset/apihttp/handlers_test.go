package apihttp_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	assetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/apihttp"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
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
	store := newFakeAssetStore()
	provider := &fakeProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	}

	handler, token := newAssetHTTPHandler(t, userID, store, provider)
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(`{"kind":"image","content_type":"image/png","metadata":{"source":"camera"}}`))
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
		UploadURL string `json:"upload_url"`
		ExpiresIn int    `json:"expires_in"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode init response: %v", err)
	}
	if body.Asset.ID == "" || body.Asset.Status != assetrepo.AssetStatusPendingUpload {
		t.Fatalf("unexpected init response: %+v", body)
	}
	if body.UploadURL != provider.putURL || body.ExpiresIn <= 0 {
		t.Fatalf("unexpected init response: %+v", body)
	}
	if bytes.Contains(rec.Body.Bytes(), []byte(`"headers"`)) {
		t.Fatalf("expected init response to omit headers, got %s", rec.Body.String())
	}
	if got := store.lastCreate.CreatedBy; got == nil || *got != userID {
		t.Fatalf("unexpected created_by: %+v", store.lastCreate.CreatedBy)
	}
	if got, want := store.lastCreate.Bucket, provider.bucket; got != want {
		t.Fatalf("bucket got %q want %q", got, want)
	}
	if got, want := store.lastCreate.StorageBackend, "minio"; got != want {
		t.Fatalf("storage backend got %q want %q", got, want)
	}
	if got := store.lastCreate.ObjectKey; !strings.HasPrefix(got, "image/") {
		t.Fatalf("unexpected object key: %q", got)
	}
}

func TestInitAssetUploadAllowsNonUUIDUserID(t *testing.T) {
	store := newFakeAssetStore()
	provider := &fakeProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	}

	handler, token := newAssetHTTPHandlerWithSubjectKey(t, "user-plain-text", store, provider)
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(`{"kind":"image","content_type":"image/png","metadata":{}}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("unexpected init status: %d body=%s", rec.Code, rec.Body.String())
	}
	if store.lastCreate.CreatedBy != nil {
		t.Fatalf("expected created_by to be nil for non-uuid user id, got %+v", store.lastCreate.CreatedBy)
	}
}

func TestInitAssetUploadRejectsUnknownFields(t *testing.T) {
	userID := uuid.New()
	handler, token := newAssetHTTPHandler(t, userID, newFakeAssetStore(), &fakeProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(`{"kind":"image","content_type":"image/png","metadata":{},"unexpected":true}`))
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
	handler, token := newAssetHTTPHandler(t, userID, newFakeAssetStore(), &fakeProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	})
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(`{"kind":"runtime-task","content_type":"image/png","metadata":{}}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid kind to be rejected, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestInitAssetUploadDoesNotRequireFollowupGetAfterCreate(t *testing.T) {
	userID := uuid.New()
	store := newFakeAssetStore()
	store.getErr = errors.New("unexpected get")
	provider := &fakeProvider{
		bucket: "assets",
		putURL: "https://object.test/upload",
	}

	handler, token := newAssetHTTPHandler(t, userID, store, provider)
	req := httptest.NewRequest(http.MethodPost, "/assets/uploads:init", bytes.NewBufferString(`{"kind":"image","content_type":"image/png","metadata":{}}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("expected init upload to avoid followup get, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestCompleteAssetUploadMarksAssetReady(t *testing.T) {
	userID := uuid.New()
	store := newFakeAssetStore()
	asset := &assetrepo.Asset{
		ID:             uuid.New(),
		Kind:           "image",
		Status:         assetrepo.AssetStatusPendingUpload,
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "image/demo-object",
		ContentType:    "image/png",
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedBy:      &userID,
	}
	store.items[asset.ID] = *asset
	provider := &fakeProvider{
		bucket: "assets",
		stat: &storage.ObjectStat{
			Size:        20,
			ContentType: "image/webp",
		},
	}

	handler, token := newAssetHTTPHandler(t, userID, store, provider)
	req := httptest.NewRequest(http.MethodPost, "/assets/"+asset.ID.String()+":complete", bytes.NewBufferString(`{"size_bytes":20,"sha256_hex":"abc123"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected complete status: %d body=%s", rec.Code, rec.Body.String())
	}
	if got, want := provider.lastStatObjectKey, asset.ObjectKey; got != want {
		t.Fatalf("stat object key got %q want %q", got, want)
	}
	if got, want := store.lastMarkReady.ID, asset.ID; got != want {
		t.Fatalf("mark ready id got %s want %s", got, want)
	}
	if got, want := store.lastMarkReady.SizeBytes, int64(20); got != want {
		t.Fatalf("mark ready size got %d want %d", got, want)
	}
	if store.lastMarkReady.Sha256Hex == nil || *store.lastMarkReady.Sha256Hex != "abc123" {
		t.Fatalf("unexpected sha256: %+v", store.lastMarkReady.Sha256Hex)
	}
	if got, want := store.lastMarkReady.ContentType, "image/webp"; got != want {
		t.Fatalf("content type got %q want %q", got, want)
	}
}

func TestCompleteAssetUploadRejectsUnknownFields(t *testing.T) {
	userID := uuid.New()
	store := newFakeAssetStore()
	asset := &assetrepo.Asset{
		ID:             uuid.New(),
		Kind:           "image",
		Status:         assetrepo.AssetStatusPendingUpload,
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "image/demo-object",
		ContentType:    "image/png",
		CreatedBy:      &userID,
	}
	store.items[asset.ID] = *asset

	handler, token := newAssetHTTPHandler(t, userID, store, &fakeProvider{
		bucket: "assets",
		stat: &storage.ObjectStat{
			Size:        20,
			ContentType: "image/png",
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/assets/"+asset.ID.String()+":complete", bytes.NewBufferString(`{"size_bytes":20,"unknown":"x"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code == http.StatusOK {
		t.Fatalf("expected unknown complete field to be rejected, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestGetAssetReturnsMetadata(t *testing.T) {
	userID := uuid.New()
	assetID := uuid.New()
	store := newFakeAssetStore()
	store.items[assetID] = assetrepo.Asset{
		ID:             assetID,
		Kind:           "image",
		Status:         assetrepo.AssetStatusReady,
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "image/demo-object",
		ContentType:    "image/png",
		SizeBytes:      20,
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedBy:      &userID,
	}

	handler, token := newAssetHTTPHandler(t, userID, store, &fakeProvider{bucket: "assets"})
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
	if body["id"] != assetID.String() || body["status"] != assetrepo.AssetStatusReady {
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
	store := newFakeAssetStore()
	store.items[assetID] = assetrepo.Asset{
		ID:             assetID,
		Kind:           "image",
		Status:         assetrepo.AssetStatusReady,
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "image/demo-object",
		ContentType:    "image/png",
	}
	provider := &fakeProvider{
		bucket: "assets",
		getURL: "https://object.test/download",
	}

	handler, token := newAssetHTTPHandler(t, userID, store, provider)
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

func newAssetHTTPHandler(t *testing.T, userID uuid.UUID, store *fakeAssetStore, provider *fakeProvider) (http.Handler, string) {
	t.Helper()

	return newAssetHTTPHandlerWithSubjectKey(t, userID.String(), store, provider)
}

func newAssetHTTPHandlerWithSubjectKey(t *testing.T, subjectKey string, store *fakeAssetStore, provider *fakeProvider) (http.Handler, string) {
	t.Helper()

	accessStore := newFakeAccessStore(subjectKey)
	authenticator := accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(accessStore)
	token, err := authenticator.IssueTokenContext(context.Background(), subjectKey)
	if err != nil {
		t.Fatalf("issue token: %v", err)
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
			Store:           store,
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

type fakeAssetStore struct {
	items         map[uuid.UUID]assetrepo.Asset
	lastCreate    assetrepo.CreatePendingParams
	lastMarkReady assetrepo.MarkReadyParams
	getErr        error
}

func newFakeAssetStore() *fakeAssetStore {
	return &fakeAssetStore{items: make(map[uuid.UUID]assetrepo.Asset)}
}

func (s *fakeAssetStore) CreatePending(_ context.Context, params assetrepo.CreatePendingParams) (*assetrepo.Asset, error) {
	s.lastCreate = params
	now := time.Now().UTC()
	asset := assetrepo.Asset{
		ID:             uuid.New(),
		Kind:           params.Kind,
		Status:         assetrepo.AssetStatusPendingUpload,
		StorageBackend: params.StorageBackend,
		Bucket:         params.Bucket,
		ObjectKey:      params.ObjectKey,
		ContentType:    params.ContentType,
		Metadata:       append([]byte(nil), params.Metadata...),
		CreatedBy:      params.CreatedBy,
		CreatedAt:      now,
		UpdatedAt:      now,
	}
	s.items[asset.ID] = asset
	copy := asset
	return &copy, nil
}

func (s *fakeAssetStore) Get(_ context.Context, id uuid.UUID) (*assetrepo.Asset, error) {
	if s.getErr != nil {
		return nil, s.getErr
	}
	asset, ok := s.items[id]
	if !ok {
		return nil, nil
	}
	copy := asset
	return &copy, nil
}

func (s *fakeAssetStore) MarkReady(_ context.Context, params assetrepo.MarkReadyParams) (*assetrepo.Asset, error) {
	s.lastMarkReady = params
	asset, ok := s.items[params.ID]
	if !ok {
		return nil, nil
	}
	if asset.Status != assetrepo.AssetStatusPendingUpload {
		return nil, nil
	}
	asset.Status = assetrepo.AssetStatusReady
	asset.SizeBytes = params.SizeBytes
	asset.Sha256Hex = params.Sha256Hex
	asset.ContentType = params.ContentType
	asset.UpdatedAt = time.Now().UTC()
	s.items[params.ID] = asset
	copy := asset
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
		permissions: []string{"assets:read", "assets:write"},
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
