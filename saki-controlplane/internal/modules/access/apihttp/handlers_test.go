package apihttp_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/google/uuid"
)

func TestLoginReturnsToken(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewBufferString(`{"user_id":"user-1","permissions":["projects:read"]}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["token"] == "" || body["user_id"] != "user-1" {
		t.Fatalf("unexpected login body: %v", body)
	}
}

func TestCurrentUserUsesBearerToken(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := loginAndExtractToken(t, handler, "user-2", []string{"projects:read"})
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

func TestPermissionDeniedReturnsForbidden(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	token := loginAndExtractToken(t, handler, "user-3", []string{"projects:read"})
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

func loginAndExtractToken(t *testing.T, handler http.Handler, userID string, permissions []string) string {
	t.Helper()

	payload, err := json.Marshal(map[string]any{
		"user_id":     userID,
		"permissions": permissions,
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
	store := newFakeAccessStore()
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(store),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
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

type fakeAnnotationStore struct{}

func (fakeAnnotationStore) Create(context.Context, annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error) {
	return nil, nil
}

func (fakeAnnotationStore) ListBySample(context.Context, uuid.UUID) ([]annotationrepo.Annotation, error) {
	return nil, nil
}

type fakeAccessStore struct {
	byUserID        map[string]*accessdomain.Principal
	permissionsByID map[uuid.UUID][]string
}

func newFakeAccessStore() *fakeAccessStore {
	return &fakeAccessStore{
		byUserID: map[string]*accessdomain.Principal{
			"user-1": {
				ID:          uuid.MustParse("00000000-0000-0000-0000-000000000101"),
				SubjectType: accessdomain.SubjectTypeUser,
				SubjectKey:  "user-1",
				DisplayName: "User One",
				Status:      accessdomain.PrincipalStatusActive,
			},
			"user-2": {
				ID:          uuid.MustParse("00000000-0000-0000-0000-000000000102"),
				SubjectType: accessdomain.SubjectTypeUser,
				SubjectKey:  "user-2",
				DisplayName: "User Two",
				Status:      accessdomain.PrincipalStatusActive,
			},
			"user-3": {
				ID:          uuid.MustParse("00000000-0000-0000-0000-000000000103"),
				SubjectType: accessdomain.SubjectTypeUser,
				SubjectKey:  "user-3",
				DisplayName: "User Three",
				Status:      accessdomain.PrincipalStatusActive,
			},
		},
		permissionsByID: map[uuid.UUID][]string{
			uuid.MustParse("00000000-0000-0000-0000-000000000101"): {"projects:read"},
			uuid.MustParse("00000000-0000-0000-0000-000000000102"): {"projects:read"},
			uuid.MustParse("00000000-0000-0000-0000-000000000103"): {"projects:read"},
		},
	}
}

func (s *fakeAccessStore) GetPrincipalByUserID(_ context.Context, userID string) (*accessdomain.Principal, error) {
	return s.byUserID[userID], nil
}

func (s *fakeAccessStore) GetPrincipalByID(_ context.Context, principalID uuid.UUID) (*accessdomain.Principal, error) {
	for _, principal := range s.byUserID {
		if principal.ID == principalID {
			return principal, nil
		}
	}
	return nil, nil
}

func (s *fakeAccessStore) ListPermissions(_ context.Context, principalID uuid.UUID) ([]string, error) {
	return append([]string(nil), s.permissionsByID[principalID]...), nil
}

func (s *fakeAccessStore) UpsertBootstrapPrincipal(context.Context, accessapp.BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	return nil, nil
}
