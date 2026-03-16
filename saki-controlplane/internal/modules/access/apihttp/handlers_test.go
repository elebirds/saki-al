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
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
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
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
	})
}

type fakeRuntimeTaskCanceler struct{}

func (fakeRuntimeTaskCanceler) Handle(context.Context, runtimecommands.CancelTaskCommand) (*runtimecommands.TaskRecord, error) {
	return &runtimecommands.TaskRecord{}, nil
}
