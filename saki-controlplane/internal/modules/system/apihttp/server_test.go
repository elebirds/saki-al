package apihttp

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
)

func TestServerHealthzReturnsJSON(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d", rec.Code)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["status"] != "ok" {
		t.Fatalf("unexpected body: %v", body)
	}
}

func TestServerReturnsStructuredErrorResponse(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/auth/permissions/projects:read", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("unexpected status: %d", rec.Code)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["code"] != "unauthorized" {
		t.Fatalf("unexpected error code: %v", body)
	}
	if body["message"] == "" {
		t.Fatalf("expected error message, got %v", body)
	}
}

func newTestHTTPHandler() (http.Handler, error) {
	return NewHTTPHandler(Dependencies{
		Authenticator: accessapp.NewAuthenticator("test-secret", time.Hour),
		ProjectStore:  projectapp.NewMemoryStore(),
		RuntimeStore:  runtimequeries.NewMemoryAdminStore(),
	})
}
