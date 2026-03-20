package apitest

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
)

func TestHumanControlPlaneManagementSmoke(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	container, dsn := startSystemSmokePostgres(t)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, systemSmokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "smoke-secret")
	t.Setenv("AUTH_TOKEN_TTL", "10m")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")
	t.Setenv("BUILD_VERSION", "smoke-build")

	server, _, err := bootstrap.NewPublicAPI(t.Context())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}
	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	setupBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/system/setup",
		`{"email":"admin@example.com","password":"secret-pass","full_name":"Initial Admin"}`,
		"",
	))
	adminAccessToken, _ := setupBody["access_token"].(string)
	adminUser, _ := setupBody["user"].(map[string]any)
	adminID, _ := adminUser["principal_id"].(string)
	if adminAccessToken == "" || adminID == "" {
		t.Fatalf("expected setup to return admin session and principal id, got %+v", setupBody)
	}

	usersResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/users?page=1&limit=20",
		"",
		adminAccessToken,
	)
	if usersResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected users status: %d body=%s", usersResp.StatusCode, readBodyString(t, usersResp))
	}
	usersBody := decodeJSONResponse(t, usersResp)
	userItems, ok := usersBody["items"].([]any)
	if !ok || len(userItems) != 1 {
		t.Fatalf("unexpected users body: %+v", usersBody)
	}
	firstUser, ok := userItems[0].(map[string]any)
	if !ok || firstUser["email"] != "admin@example.com" {
		t.Fatalf("unexpected first user payload: %+v", usersBody)
	}

	rolesResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/roles?page=1&limit=20&type=system",
		"",
		adminAccessToken,
	)
	if rolesResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected roles status: %d body=%s", rolesResp.StatusCode, readBodyString(t, rolesResp))
	}
	rolesBody := decodeJSONResponse(t, rolesResp)
	roleItems, ok := rolesBody["items"].([]any)
	if !ok || len(roleItems) == 0 {
		t.Fatalf("unexpected roles body: %+v", rolesBody)
	}
	roleNames := make([]string, 0, len(roleItems))
	for _, item := range roleItems {
		row, ok := item.(map[string]any)
		if !ok {
			t.Fatalf("unexpected role payload: %+v", rolesBody)
		}
		name, _ := row["name"].(string)
		roleNames = append(roleNames, name)
	}
	if !slices.Contains(roleNames, "super_admin") {
		t.Fatalf("expected super_admin role, got %+v", rolesBody)
	}
	firstRole, ok := roleItems[0].(map[string]any)
	if !ok || firstRole["built_in"] == nil || firstRole["mutable"] == nil || firstRole["sort_order"] == nil {
		t.Fatalf("expected role metadata fields, got %+v", rolesBody)
	}

	systemPermissionsResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/system",
		"",
		adminAccessToken,
	)
	if systemPermissionsResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected system permissions status: %d body=%s", systemPermissionsResp.StatusCode, readBodyString(t, systemPermissionsResp))
	}
	systemPermissionsBody := decodeJSONResponse(t, systemPermissionsResp)
	if systemPermissionsBody["user_id"] != "admin@example.com" {
		t.Fatalf("unexpected system permissions body: %+v", systemPermissionsBody)
	}
	if _, ok := systemPermissionsBody["system_roles"].([]any); !ok {
		t.Fatalf("expected system_roles in permissions snapshot, got %+v", systemPermissionsBody)
	}

	catalogResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/roles/permission-catalog",
		"",
		adminAccessToken,
	)
	if catalogResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected permission catalog status: %d body=%s", catalogResp.StatusCode, readBodyString(t, catalogResp))
	}
	catalogBody := decodeJSONResponse(t, catalogResp)
	allPermissions, ok := catalogBody["all_permissions"].([]any)
	if !ok || len(allPermissions) == 0 {
		t.Fatalf("unexpected permission catalog body: %+v", catalogBody)
	}

	userRolesResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/users/"+adminID+"/system-roles",
		"",
		adminAccessToken,
	)
	if userRolesResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected user system roles status: %d body=%s", userRolesResp.StatusCode, readBodyString(t, userRolesResp))
	}
	userRolesBody := decodeJSONArrayResponse(t, userRolesResp)
	if len(userRolesBody) == 0 {
		t.Fatalf("expected admin to have at least one system role binding, got %+v", userRolesBody)
	}
	if userRolesBody[0]["role_name"] != "super_admin" {
		t.Fatalf("expected super_admin system role binding, got %+v", userRolesBody)
	}

	legacyUserRolesResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/roles/users/"+adminID+"/roles",
		"",
		adminAccessToken,
	)
	if legacyUserRolesResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected legacy user system roles status: %d body=%s", legacyUserRolesResp.StatusCode, readBodyString(t, legacyUserRolesResp))
	}
	legacyUserRolesBody := decodeJSONArrayResponse(t, legacyUserRolesResp)
	if len(legacyUserRolesBody) == 0 || legacyUserRolesBody[0]["role_name"] != "super_admin" {
		t.Fatalf("expected legacy alias to expose same system role binding, got %+v", legacyUserRolesBody)
	}
}

func decodeJSONArrayResponse(t *testing.T, resp *http.Response) []map[string]any {
	t.Helper()
	defer resp.Body.Close()

	var body []map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode array response: %v", err)
	}
	if resp.StatusCode >= http.StatusBadRequest {
		t.Fatalf("unexpected error response: status=%d body=%+v", resp.StatusCode, body)
	}
	return body
}
