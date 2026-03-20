package apihttp_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"
	"time"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/google/uuid"
)

func TestLoginReturnsRepoBackedPermissions(t *testing.T) {
	store := newFakeAccessStore()
	handler, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewBufferString(`{"user_id":"user-1"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body struct {
		Token       string   `json:"token"`
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.Token == "" || body.UserID != "user-1" {
		t.Fatalf("unexpected login body: %v", body)
	}
	if !slices.Equal(body.Permissions, []string{"projects:read"}) {
		t.Fatalf("expected authorizer-backed permissions, got %+v", body)
	}
	if store.loadByUserIDCalls != 1 {
		t.Fatalf("expected one aggregate user lookup, got %d", store.loadByUserIDCalls)
	}
}

func TestLoginRejectsUnknownPrincipal(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewBufferString(`{"user_id":"missing-user"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestLoginRejectsDisabledPrincipal(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewBufferString(`{"user_id":"disabled-user"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestCurrentUserUsesBearerToken(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := loginAndExtractToken(t, handler, "user-2")
	req := httptest.NewRequest(http.MethodGet, "/auth/me", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["user_id"] != "user-2" {
		t.Fatalf("unexpected current user body: %v", body)
	}
}

func TestMiddlewareReloadsClaimsThroughAggregateLoader(t *testing.T) {
	store := newFakeAccessStore()
	handler, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := loginAndExtractToken(t, handler, "user-2")
	principalID := store.claimsByUserID["user-2"].PrincipalID
	store.claimsByPrincipalID[principalID] = &accessapp.ClaimsSnapshot{
		PrincipalID: principalID,
		UserID:      "user-2",
		Permissions: []string{"projects:write"},
	}

	req := httptest.NewRequest(http.MethodGet, "/auth/me", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body struct {
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode current user response: %v", err)
	}
	if body.UserID != "user-2" {
		t.Fatalf("unexpected current user body: %+v", body)
	}
	if !slices.Equal(body.Permissions, []string{"projects:write"}) {
		t.Fatalf("expected reloaded aggregate permissions, got %+v", body)
	}
	if store.loadByPrincipalIDCalls == 0 {
		t.Fatal("expected middleware to reload claims by principal id")
	}
}

func TestMiddlewareRejectsDisabledPrincipal(t *testing.T) {
	store := newFakeAccessStore()
	handler, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := loginAndExtractToken(t, handler, "user-2")
	principalID := store.claimsByUserID["user-2"].PrincipalID
	store.loadByPrincipalErr[principalID] = accessapp.ErrUnauthorized

	req := httptest.NewRequest(http.MethodGet, "/auth/me", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestPermissionDeniedReturnsForbidden(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := loginAndExtractToken(t, handler, "user-3")
	req := httptest.NewRequest(http.MethodGet, "/auth/permissions/projects:write", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["code"] != "forbidden" {
		t.Fatalf("unexpected error body: %v", body)
	}
}

func loginAndExtractToken(t *testing.T, handler http.Handler, userID string) string {
	t.Helper()

	payload, err := json.Marshal(map[string]any{
		"user_id": userID,
	})
	if err != nil {
		t.Fatalf("marshal login payload: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("login failed: status=%d body=%s", rec.Code, rec.Body.String())
	}

	var body struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode login response: %v", err)
	}
	if body.Token == "" {
		t.Fatal("expected token")
	}

	return body.Token
}

func newTestHTTPHandler() (http.Handler, error) {
	return newTestHTTPHandlerWithStore(newFakeAccessStore())
}

func newTestHTTPHandlerWithStore(store *fakeAccessStore) (http.Handler, error) {
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(store),
		ClaimsStore:         store,
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
	})
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

type fakeAccessStore struct {
	claimsByUserID         map[string]*accessapp.ClaimsSnapshot
	claimsByPrincipalID    map[uuid.UUID]*accessapp.ClaimsSnapshot
	loadByUserIDErr        map[string]error
	loadByPrincipalErr     map[uuid.UUID]error
	loadByUserIDCalls      int
	loadByPrincipalIDCalls int
}

func newFakeAccessStore() *fakeAccessStore {
	return &fakeAccessStore{
		claimsByUserID: map[string]*accessapp.ClaimsSnapshot{
			"user-1": {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000000101"),
				UserID:      "user-1",
				Permissions: []string{"projects:read"},
			},
			"user-2": {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000000102"),
				UserID:      "user-2",
				Permissions: []string{"projects:read"},
			},
			"user-3": {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000000103"),
				UserID:      "user-3",
				Permissions: []string{"projects:read"},
			},
		},
		claimsByPrincipalID: map[uuid.UUID]*accessapp.ClaimsSnapshot{
			uuid.MustParse("00000000-0000-0000-0000-000000000101"): {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000000101"),
				UserID:      "user-1",
				Permissions: []string{"projects:read"},
			},
			uuid.MustParse("00000000-0000-0000-0000-000000000102"): {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000000102"),
				UserID:      "user-2",
				Permissions: []string{"projects:read"},
			},
			uuid.MustParse("00000000-0000-0000-0000-000000000103"): {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000000103"),
				UserID:      "user-3",
				Permissions: []string{"projects:read"},
			},
		},
		loadByUserIDErr: map[string]error{
			"disabled-user": accessapp.ErrUnauthorized,
		},
		loadByPrincipalErr: map[uuid.UUID]error{},
	}
}

func (s *fakeAccessStore) LoadClaimsByUserID(_ context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	s.loadByUserIDCalls++
	if err := s.loadByUserIDErr[userID]; err != nil {
		return nil, err
	}
	return cloneAccessClaims(s.claimsByUserID[userID]), nil
}

func (s *fakeAccessStore) LoadClaimsByPrincipalID(_ context.Context, principalID uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	s.loadByPrincipalIDCalls++
	if err := s.loadByPrincipalErr[principalID]; err != nil {
		return nil, err
	}
	return cloneAccessClaims(s.claimsByPrincipalID[principalID]), nil
}

func (s *fakeAccessStore) UpsertBootstrapPrincipal(context.Context, accessapp.BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	return nil, nil
}

func cloneAccessClaims(claims *accessapp.ClaimsSnapshot) *accessapp.ClaimsSnapshot {
	if claims == nil {
		return nil
	}
	cloned := *claims
	cloned.Permissions = append([]string(nil), claims.Permissions...)
	return &cloned
}
