package publicapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestWithRemovedRoutesReturns404BeforeNext(t *testing.T) {
	nextCalled := false
	handler := WithRemovedRoutes(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nextCalled = true
		w.WriteHeader(http.StatusUnauthorized)
	}), RemovedRoute{
		Method:      http.MethodPost,
		PathPattern: "/system/setup",
	})

	req := httptest.NewRequest(http.MethodPost, "/system/setup", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec.Code)
	}
	if nextCalled {
		t.Fatalf("expected removed route middleware to short-circuit before next handler")
	}
}

func TestWithRemovedRoutesMatchesParameterizedPattern(t *testing.T) {
	nextCalled := false
	handler := WithRemovedRoutes(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nextCalled = true
		w.WriteHeader(http.StatusOK)
	}), RemovedRoute{
		Method:      http.MethodGet,
		PathPattern: "/roles/users/{principal_id}/roles",
	})

	req := httptest.NewRequest(http.MethodGet, "/roles/users/00000000-0000-0000-0000-000000001499/roles", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec.Code)
	}
	if nextCalled {
		t.Fatalf("expected parameterized removed route to short-circuit before next handler")
	}
}

func TestWithRemovedRoutesFallsThroughWhenRouteDoesNotMatch(t *testing.T) {
	nextCalled := false
	handler := WithRemovedRoutes(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nextCalled = true
		w.WriteHeader(http.StatusNoContent)
	}), RemovedRoute{
		Method:      http.MethodGet,
		PathPattern: "/roles/users/{principal_id}/roles",
	})

	req := httptest.NewRequest(http.MethodGet, "/users/00000000-0000-0000-0000-000000001499/system-roles", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("expected next handler status, got %d", rec.Code)
	}
	if !nextCalled {
		t.Fatalf("expected non-removed route to fall through to next handler")
	}
}
