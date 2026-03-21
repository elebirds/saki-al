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

	initBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/system/init",
		`{"email":"admin@example.com","password":"secret-pass","full_name":"Initial Admin"}`,
		"",
	))
	adminAccessToken, _ := initBody["access_token"].(string)
	adminUser, _ := initBody["user"].(map[string]any)
	adminID, _ := adminUser["principal_id"].(string)
	if adminAccessToken == "" || adminID == "" {
		t.Fatalf("expected init to return admin session and principal id, got %+v", initBody)
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
	systemPermissions, ok := systemPermissionsBody["permissions"].([]any)
	if !ok || len(systemPermissions) == 0 {
		t.Fatalf("unexpected system permissions body: %+v", systemPermissionsBody)
	}
	if _, ok := systemPermissionsBody["user_id"]; ok {
		t.Fatalf("latest /permissions/system should not expose current-user snapshot fields, got %+v", systemPermissionsBody)
	}

	resourcePermissionsResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/resource",
		"",
		adminAccessToken,
	)
	if resourcePermissionsResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected resource permissions status: %d body=%s", resourcePermissionsResp.StatusCode, readBodyString(t, resourcePermissionsResp))
	}
	resourcePermissionsBody := decodeJSONResponse(t, resourcePermissionsResp)
	resourcePermissions, ok := resourcePermissionsBody["permissions"].([]any)
	if !ok || len(resourcePermissions) == 0 {
		t.Fatalf("unexpected resource permissions body: %+v", resourcePermissionsBody)
	}
	resourceRoles, ok := resourcePermissionsBody["roles"].([]any)
	if !ok || len(resourceRoles) == 0 {
		t.Fatalf("expected resource role definitions, got %+v", resourcePermissionsBody)
	}
	firstResourceRole, ok := resourceRoles[0].(map[string]any)
	if !ok || firstResourceRole["resource_type"] == nil || firstResourceRole["name"] == nil || firstResourceRole["assignable"] == nil {
		t.Fatalf("expected resource role definition metadata, got %+v", resourcePermissionsBody)
	}
	if _, ok := resourcePermissionsBody["resource_role"]; ok {
		t.Fatalf("latest /permissions/resource should expose catalog only, got %+v", resourcePermissionsBody)
	}

	catalogResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/catalog",
		"",
		adminAccessToken,
	)
	if catalogResp.StatusCode != http.StatusNotFound {
		t.Fatalf("expected removed permission catalog endpoint to return 404, got %d body=%s", catalogResp.StatusCode, readBodyString(t, catalogResp))
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
	if userRolesBody[0]["principal_id"] != adminID {
		t.Fatalf("expected user system role binding to expose principal_id=%s, got %+v", adminID, userRolesBody)
	}
	if userRolesBody[0]["role_name"] != "super_admin" {
		t.Fatalf("expected super_admin system role binding, got %+v", userRolesBody)
	}
	if _, ok := userRolesBody[0]["user_id"]; ok {
		t.Fatalf("latest user system role binding should not expose legacy user_id, got %+v", userRolesBody)
	}

	removedCatalogResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/roles/permission-catalog",
		"",
		adminAccessToken,
	)
	if removedCatalogResp.StatusCode != http.StatusNotFound {
		t.Fatalf("expected removed permission catalog alias to return 404, got %d body=%s", removedCatalogResp.StatusCode, readBodyString(t, removedCatalogResp))
	}

	removedUserRolesResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/roles/users/"+adminID+"/roles",
		"",
		adminAccessToken,
	)
	if removedUserRolesResp.StatusCode != http.StatusNotFound {
		t.Fatalf("expected removed user system roles alias to return 404, got %d body=%s", removedUserRolesResp.StatusCode, readBodyString(t, removedUserRolesResp))
	}
}

func TestHumanControlPlaneManagementWriteSmoke(t *testing.T) {
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

	initBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/system/init",
		`{"email":"admin@example.com","password":"secret-pass","full_name":"Initial Admin"}`,
		"",
	))
	adminAccessToken, _ := initBody["access_token"].(string)
	if adminAccessToken == "" {
		t.Fatalf("expected init to return admin session, got %+v", initBody)
	}

	createRoleResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/roles",
		`{"name":"auditor","display_name":"Auditor","description":"Read-only audit role","color":"cyan","permissions":["users:read","roles:read"]}`,
		adminAccessToken,
	)
	if createRoleResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected create role status: %d body=%s", createRoleResp.StatusCode, readBodyString(t, createRoleResp))
	}
	roleBody := decodeJSONResponse(t, createRoleResp)
	roleID, _ := roleBody["id"].(string)
	if roleID == "" || roleBody["name"] != "auditor" {
		t.Fatalf("unexpected role body: %+v", roleBody)
	}

	getRoleResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/roles/"+roleID,
		"",
		adminAccessToken,
	)
	if getRoleResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected get role status: %d body=%s", getRoleResp.StatusCode, readBodyString(t, getRoleResp))
	}
	gotRoleBody := decodeJSONResponse(t, getRoleResp)
	if gotRoleBody["id"] != roleID || gotRoleBody["name"] != "auditor" {
		t.Fatalf("unexpected role detail body: %+v", gotRoleBody)
	}

	updateRoleResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPatch,
		httpServer.URL+"/roles/"+roleID,
		`{"display_name":"Security Auditor","color":"geekblue","permissions":["users:read"]}`,
		adminAccessToken,
	)
	if updateRoleResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected update role status: %d body=%s", updateRoleResp.StatusCode, readBodyString(t, updateRoleResp))
	}
	updatedRoleBody := decodeJSONResponse(t, updateRoleResp)
	if updatedRoleBody["display_name"] != "Security Auditor" || updatedRoleBody["color"] != "geekblue" {
		t.Fatalf("unexpected updated role body: %+v", updatedRoleBody)
	}

	createUserResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/users",
		`{"email":"auditor@example.com","password":"temp-pass","full_name":"Audit User","is_active":true}`,
		adminAccessToken,
	)
	if createUserResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected create user status: %d body=%s", createUserResp.StatusCode, readBodyString(t, createUserResp))
	}
	userBody := decodeJSONResponse(t, createUserResp)
	userID, _ := userBody["id"].(string)
	if userID == "" || userBody["email"] != "auditor@example.com" {
		t.Fatalf("unexpected user body: %+v", userBody)
	}
	if userBody["must_change_password"] != true {
		t.Fatalf("expected admin-created user to require password change, got %+v", userBody)
	}

	getUserResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/users/"+userID,
		"",
		adminAccessToken,
	)
	if getUserResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected get user status: %d body=%s", getUserResp.StatusCode, readBodyString(t, getUserResp))
	}
	gotUserBody := decodeJSONResponse(t, getUserResp)
	if gotUserBody["id"] != userID || gotUserBody["email"] != "auditor@example.com" {
		t.Fatalf("unexpected user detail body: %+v", gotUserBody)
	}

	replaceRolesResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPut,
		httpServer.URL+"/users/"+userID+"/system-roles",
		`{"role_ids":["`+roleID+`"]}`,
		adminAccessToken,
	)
	if replaceRolesResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected replace user roles status: %d body=%s", replaceRolesResp.StatusCode, readBodyString(t, replaceRolesResp))
	}
	replacedRolesBody := decodeJSONArrayResponse(t, replaceRolesResp)
	if len(replacedRolesBody) != 1 || replacedRolesBody[0]["role_id"] != roleID {
		t.Fatalf("unexpected replaced roles body: %+v", replacedRolesBody)
	}
	if replacedRolesBody[0]["principal_id"] != userID {
		t.Fatalf("expected replaced roles body to expose principal_id=%s, got %+v", userID, replacedRolesBody)
	}
	if _, ok := replacedRolesBody[0]["user_id"]; ok {
		t.Fatalf("latest replaced roles body should not expose legacy user_id, got %+v", replacedRolesBody)
	}

	updateUserResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPatch,
		httpServer.URL+"/users/"+userID,
		`{"full_name":"Audit User Updated","is_active":false}`,
		adminAccessToken,
	)
	if updateUserResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected update user status: %d body=%s", updateUserResp.StatusCode, readBodyString(t, updateUserResp))
	}
	updatedUserBody := decodeJSONResponse(t, updateUserResp)
	if updatedUserBody["full_name"] != "Audit User Updated" || updatedUserBody["is_active"] != false {
		t.Fatalf("unexpected updated user body: %+v", updatedUserBody)
	}

	deleteUserResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodDelete,
		httpServer.URL+"/users/"+userID,
		"",
		adminAccessToken,
	)
	if deleteUserResp.StatusCode != http.StatusNoContent {
		t.Fatalf("unexpected delete user status: %d body=%s", deleteUserResp.StatusCode, readBodyString(t, deleteUserResp))
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
		t.Fatalf("unexpected users status after delete: %d body=%s", usersResp.StatusCode, readBodyString(t, usersResp))
	}
	usersBody := decodeJSONResponse(t, usersResp)
	items, ok := usersBody["items"].([]any)
	if !ok {
		t.Fatalf("unexpected users body after delete: %+v", usersBody)
	}
	for _, item := range items {
		row, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if row["id"] == userID {
			t.Fatalf("expected deleted user to disappear from list, got %+v", usersBody)
		}
	}

	deleteRoleResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodDelete,
		httpServer.URL+"/roles/"+roleID,
		"",
		adminAccessToken,
	)
	if deleteRoleResp.StatusCode != http.StatusNoContent {
		t.Fatalf("unexpected delete role status: %d body=%s", deleteRoleResp.StatusCode, readBodyString(t, deleteRoleResp))
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
