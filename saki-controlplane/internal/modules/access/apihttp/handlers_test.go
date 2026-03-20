package apihttp_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
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

func TestPermissionGrantedReturnsNoContent(t *testing.T) {
	store := newFakeAccessStore()
	handler, authenticator, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := issueAccessToken(t, authenticator, "user-1")
	req := httptest.NewRequest(http.MethodGet, "/auth/permissions/projects:read", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestMiddlewareReloadsClaimsThroughAggregateLoader(t *testing.T) {
	store := newFakeAccessStore()
	handler, authenticator, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := issueAccessToken(t, authenticator, "user-2")
	principalID := store.claimsByUserID["user-2"].PrincipalID
	store.claimsByPrincipalID[principalID] = &accessapp.ClaimsSnapshot{
		PrincipalID: principalID,
		UserID:      "user-2",
		Permissions: []string{"projects:write"},
	}

	req := httptest.NewRequest(http.MethodGet, "/auth/permissions/projects:write", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
	if store.loadByPrincipalIDCalls == 0 {
		t.Fatal("expected middleware to reload claims by principal id")
	}
}

func TestMiddlewareRejectsDisabledPrincipal(t *testing.T) {
	store := newFakeAccessStore()
	handler, authenticator, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := issueAccessToken(t, authenticator, "user-2")
	principalID := store.claimsByUserID["user-2"].PrincipalID
	store.loadByPrincipalErr[principalID] = accessapp.ErrUnauthorized

	req := httptest.NewRequest(http.MethodGet, "/auth/permissions/projects:read", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestPermissionDeniedReturnsForbidden(t *testing.T) {
	store := newFakeAccessStore()
	handler, authenticator, err := newTestHTTPHandlerWithStore(store)
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := issueAccessToken(t, authenticator, "user-3")
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

func issueAccessToken(t *testing.T, authenticator *accessapp.Authenticator, userID string) string {
	t.Helper()

	token, err := authenticator.IssueTokenContext(context.Background(), userID)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}

func newTestHTTPHandlerWithStore(store *fakeAccessStore) (http.Handler, *accessapp.Authenticator, error) {
	authenticator := accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(store)
	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       authenticator,
		ClaimsStore:         store,
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
	})
	if err != nil {
		return nil, nil, err
	}
	return handler, authenticator, nil
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
	claimsByUserID      map[string]*accessapp.ClaimsSnapshot
	claimsByPrincipalID map[uuid.UUID]*accessapp.ClaimsSnapshot
	loadByUserIDErr     map[string]error
	loadByPrincipalErr  map[uuid.UUID]error
	loadByUserIDCalls   int
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
		loadByUserIDErr:    map[string]error{},
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

func (s *fakeAccessStore) LoadBootstrapClaimsByUserID(_ context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	return cloneAccessClaims(s.claimsByUserID[userID]), nil
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
