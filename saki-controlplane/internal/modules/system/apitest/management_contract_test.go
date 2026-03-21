package apitest

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHumanControlPlaneUsersListContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/users?page=1&limit=20", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode users body: %v", err)
	}
	items, ok := body["items"].([]any)
	if !ok || len(items) == 0 {
		t.Fatalf("unexpected users body: %+v", body)
	}
	first, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("unexpected first user item: %+v", body)
	}
	if _, ok := first["id"].(string); !ok {
		t.Fatalf("expected user id field, got %+v", first)
	}
	if _, ok := first["email"].(string); !ok {
		t.Fatalf("expected user email field, got %+v", first)
	}
	if _, ok := first["is_active"].(bool); !ok {
		t.Fatalf("expected user is_active field, got %+v", first)
	}
	if _, ok := first["roles"].([]any); !ok {
		t.Fatalf("expected user roles field, got %+v", first)
	}
}

func TestHumanControlPlaneUsersListRejectsLegacyPermissionAlias(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{permissions: []string{"user:read:all"}})
	token := issueSystemTokenWithPermissions(t, "admin@example.com", []string{"user:read:all"})

	req := httptest.NewRequest(http.MethodGet, "/users?page=1&limit=20", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneRolesListContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/roles?page=1&limit=20&type=system", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode roles body: %v", err)
	}
	items, ok := body["items"].([]any)
	if !ok || len(items) == 0 {
		t.Fatalf("unexpected roles body: %+v", body)
	}
	first, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("unexpected first role item: %+v", body)
	}
	if _, ok := first["name"].(string); !ok {
		t.Fatalf("expected role name field, got %+v", first)
	}
	if _, ok := first["type"].(string); !ok {
		t.Fatalf("expected role type field, got %+v", first)
	}
	if _, ok := first["built_in"].(bool); !ok {
		t.Fatalf("expected role built_in field, got %+v", first)
	}
	if _, ok := first["mutable"].(bool); !ok {
		t.Fatalf("expected role mutable field, got %+v", first)
	}
	if _, ok := first["color"].(string); !ok {
		t.Fatalf("expected role color field, got %+v", first)
	}
	if _, ok := first["is_supremo"].(bool); !ok {
		t.Fatalf("expected role is_supremo field, got %+v", first)
	}
	if _, ok := first["sort_order"].(float64); !ok {
		t.Fatalf("expected role sort_order field, got %+v", first)
	}
	if _, ok := first["permissions"].([]any); !ok {
		t.Fatalf("expected role permissions field, got %+v", first)
	}
}

func TestHumanControlPlaneRolesListRejectsLegacyPermissionAlias(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{permissions: []string{"role:read:all"}})
	token := issueSystemTokenWithPermissions(t, "admin@example.com", []string{"role:read:all"})

	req := httptest.NewRequest(http.MethodGet, "/roles?page=1&limit=20&type=system", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneReplaceUserSystemRolesRejectsLegacyPermissionAlias(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{permissions: []string{"role:assign:all", "role:revoke:all"}})
	token := issueSystemTokenWithPermissions(t, "admin@example.com", []string{"role:assign:all", "role:revoke:all"})

	req := httptest.NewRequest(
		http.MethodPut,
		"/users/00000000-0000-0000-0000-000000001500/system-roles",
		bytes.NewBufferString(`{"role_ids":["00000000-0000-0000-0000-000000001501"]}`),
	)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneSystemPermissionsContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/permissions/system", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode system permissions body: %v", err)
	}
	if _, ok := body["permissions"].([]any); !ok {
		t.Fatalf("expected permissions field, got %+v", body)
	}
	if _, ok := body["user_id"]; ok {
		t.Fatalf("latest /permissions/system should not expose user snapshot fields, got %+v", body)
	}
	if _, ok := body["system_roles"]; ok {
		t.Fatalf("latest /permissions/system should not expose role snapshot fields, got %+v", body)
	}
	if _, ok := body["is_super_admin"]; ok {
		t.Fatalf("latest /permissions/system should not expose super-admin snapshot field, got %+v", body)
	}
}

func TestHumanControlPlaneResourcePermissionsContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/permissions/resource", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode resource permissions body: %v", err)
	}
	if _, ok := body["permissions"].([]any); !ok {
		t.Fatalf("expected permissions field, got %+v", body)
	}
	roles, ok := body["roles"].([]any)
	if !ok || len(roles) == 0 {
		t.Fatalf("expected roles field, got %+v", body)
	}
	first, ok := roles[0].(map[string]any)
	if !ok {
		t.Fatalf("unexpected first role definition: %+v", body)
	}
	if _, ok := first["resource_type"].(string); !ok {
		t.Fatalf("expected resource_type field, got %+v", first)
	}
	if _, ok := first["name"].(string); !ok {
		t.Fatalf("expected name field, got %+v", first)
	}
	if _, ok := first["permissions"].([]any); !ok {
		t.Fatalf("expected permissions field in role definition, got %+v", first)
	}
	if _, ok := first["assignable"].(bool); !ok {
		t.Fatalf("expected assignable field in role definition, got %+v", first)
	}
	if _, ok := first["resource_role"]; ok {
		t.Fatalf("latest /permissions/resource should be catalog, not current-user snapshot, got %+v", body)
	}
}

func TestHumanControlPlaneRemovedPermissionCatalogEndpointReturns404(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/permissions/catalog", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneRemovedPermissionCatalogAliasReturns404(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/roles/permission-catalog", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneUserSystemRolesRejectInvalidPrincipalID(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/users/not-a-uuid/system-roles", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneRemovedUserSystemRolesAliasReturns404(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/roles/users/00000000-0000-0000-0000-000000001499/roles", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneUserSystemRolesContracts(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/users/00000000-0000-0000-0000-000000001499/system-roles", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body []map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode user roles body: %v", err)
	}
	if len(body) == 0 {
		t.Fatalf("expected at least one role binding, got %+v", body)
	}
	if _, ok := body[0]["principal_id"].(string); !ok {
		t.Fatalf("expected principal_id field, got %+v", body[0])
	}
	if _, ok := body[0]["role_id"].(string); !ok {
		t.Fatalf("expected role_id field, got %+v", body[0])
	}
	if _, ok := body[0]["role_name"].(string); !ok {
		t.Fatalf("expected role_name field, got %+v", body[0])
	}
	if _, ok := body[0]["user_id"]; ok {
		t.Fatalf("latest user system role binding should not expose legacy user_id, got %+v", body[0])
	}
}
