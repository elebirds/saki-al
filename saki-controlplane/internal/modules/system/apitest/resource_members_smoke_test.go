package apitest

import (
	"database/sql"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
)

func TestHumanControlPlaneResourceMembersSmoke(t *testing.T) {
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
	if adminAccessToken == "" {
		t.Fatalf("expected setup to return admin session, got %+v", setupBody)
	}
	adminUser, ok := setupBody["user"].(map[string]any)
	if !ok {
		t.Fatalf("expected setup user payload, got %+v", setupBody)
	}
	adminPrincipalID, _ := adminUser["principal_id"].(string)
	if adminPrincipalID == "" {
		t.Fatalf("expected admin principal id, got %+v", setupBody)
	}

	createUserBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/users",
		`{"email":"member@example.com","password":"member-pass","full_name":"Resource Member","is_active":true}`,
		adminAccessToken,
	))
	memberID, _ := createUserBody["id"].(string)
	if memberID == "" {
		t.Fatalf("expected created member id, got %+v", createUserBody)
	}

	memberLoginBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/auth/login",
		`{"identifier":"member@example.com","password":"member-pass"}`,
		"",
	))
	memberAccessToken, _ := memberLoginBody["access_token"].(string)
	if memberAccessToken == "" {
		t.Fatalf("expected member login session, got %+v", memberLoginBody)
	}

	createDatasetResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/datasets",
		`{"name":"Smoke Dataset","type":"image_classification"}`,
		adminAccessToken,
	)
	if createDatasetResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected create dataset status: %d body=%s", createDatasetResp.StatusCode, readBodyString(t, createDatasetResp))
	}
	datasetBody := decodeJSONResponse(t, createDatasetResp)
	datasetID, _ := datasetBody["id"].(string)
	if datasetID == "" {
		t.Fatalf("expected dataset id, got %+v", datasetBody)
	}
	createOtherDatasetResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/datasets",
		`{"name":"Other Dataset","type":"image_classification"}`,
		adminAccessToken,
	)
	if createOtherDatasetResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected create other dataset status: %d body=%s", createOtherDatasetResp.StatusCode, readBodyString(t, createOtherDatasetResp))
	}
	otherDatasetBody := decodeJSONResponse(t, createOtherDatasetResp)
	otherDatasetID, _ := otherDatasetBody["id"].(string)
	if otherDatasetID == "" {
		t.Fatalf("expected other dataset id, got %+v", otherDatasetBody)
	}

	createProjectResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/projects",
		`{"name":"Smoke Project"}`,
		adminAccessToken,
	)
	if createProjectResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected create project status: %d body=%s", createProjectResp.StatusCode, readBodyString(t, createProjectResp))
	}
	projectBody := decodeJSONResponse(t, createProjectResp)
	projectID, _ := projectBody["id"].(string)
	if projectID == "" {
		t.Fatalf("expected project id, got %+v", projectBody)
	}
	createOtherProjectResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/projects",
		`{"name":"Other Project"}`,
		adminAccessToken,
	)
	if createOtherProjectResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected create other project status: %d body=%s", createOtherProjectResp.StatusCode, readBodyString(t, createOtherProjectResp))
	}
	otherProjectBody := decodeJSONResponse(t, createOtherProjectResp)
	otherProjectID, _ := otherProjectBody["id"].(string)
	if otherProjectID == "" {
		t.Fatalf("expected other project id, got %+v", otherProjectBody)
	}

	datasetRolesBody := decodeJSONArrayResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/datasets/"+datasetID+"/available-roles",
		"",
		adminAccessToken,
	))
	if len(datasetRolesBody) == 0 {
		t.Fatalf("expected dataset roles, got %+v", datasetRolesBody)
	}
	var datasetContributorRoleID string
	for _, role := range datasetRolesBody {
		if role["name"] == "dataset_contributor" {
			datasetContributorRoleID, _ = role["id"].(string)
		}
		if role["name"] == "dataset_owner" {
			t.Fatalf("owner role should not be assignable, got %+v", datasetRolesBody)
		}
	}
	if datasetContributorRoleID == "" {
		t.Fatalf("expected dataset_contributor role, got %+v", datasetRolesBody)
	}
	datasetOwnerRoleID := lookupRoleIDByName(t, sqlDB, "dataset_owner")
	datasetViewerRoleID := lookupRoleIDByName(t, sqlDB, "dataset_viewer")

	projectRolesBody := decodeJSONArrayResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/projects/"+projectID+"/available-roles",
		"",
		adminAccessToken,
	))
	if len(projectRolesBody) == 0 {
		t.Fatalf("expected project roles, got %+v", projectRolesBody)
	}
	var projectManagerRoleID string
	for _, role := range projectRolesBody {
		if role["name"] == "project_manager" {
			projectManagerRoleID, _ = role["id"].(string)
		}
		if role["name"] == "project_owner" {
			t.Fatalf("owner role should not be assignable, got %+v", projectRolesBody)
		}
	}
	if projectManagerRoleID == "" {
		t.Fatalf("expected project_manager role, got %+v", projectRolesBody)
	}

	addDatasetMemberResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/datasets/"+datasetID+"/members",
		`{"user_id":"`+memberID+`","role_id":"`+datasetContributorRoleID+`"}`,
		adminAccessToken,
	)
	if addDatasetMemberResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected add dataset member status: %d body=%s", addDatasetMemberResp.StatusCode, readBodyString(t, addDatasetMemberResp))
	}

	datasetMembersBody := decodeJSONArrayResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/datasets/"+datasetID+"/members",
		"",
		adminAccessToken,
	))
	if len(datasetMembersBody) != 1 || datasetMembersBody[0]["user_id"] != memberID {
		t.Fatalf("unexpected dataset members body: %+v", datasetMembersBody)
	}

	datasetPermissionsBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/resource?resource_type=dataset&resource_id="+datasetID,
		"",
		memberAccessToken,
	))
	resourceRole, ok := datasetPermissionsBody["resource_role"].(map[string]any)
	if !ok || resourceRole["name"] != "dataset_contributor" {
		t.Fatalf("unexpected dataset resource permissions body: %+v", datasetPermissionsBody)
	}
	permissions, ok := datasetPermissionsBody["permissions"].([]any)
	if !ok || !slices.Contains(permissions, any("dataset:update:assigned")) {
		t.Fatalf("expected dataset contributor permissions, got %+v", datasetPermissionsBody)
	}
	if datasetPermissionsBody["is_owner"] != false {
		t.Fatalf("expected dataset contributor not owner, got %+v", datasetPermissionsBody)
	}
	otherDatasetPermissionsBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/resource?resource_type=dataset&resource_id="+otherDatasetID,
		"",
		memberAccessToken,
	))
	if _, ok := otherDatasetPermissionsBody["resource_role"]; ok {
		t.Fatalf("expected no leaked resource role on unrelated dataset, got %+v", otherDatasetPermissionsBody)
	}
	otherDatasetPermissions, ok := otherDatasetPermissionsBody["permissions"].([]any)
	if !ok || len(otherDatasetPermissions) != 0 || otherDatasetPermissionsBody["is_owner"] != false {
		t.Fatalf("expected empty unrelated dataset permission snapshot, got %+v", otherDatasetPermissionsBody)
	}
	forbiddenDatasetMembersResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/datasets/"+otherDatasetID+"/members",
		"",
		memberAccessToken,
	)
	if forbiddenDatasetMembersResp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected dataset membership scope isolation, got %d body=%s", forbiddenDatasetMembersResp.StatusCode, readBodyString(t, forbiddenDatasetMembersResp))
	}

	addProjectMemberResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/projects/"+projectID+"/members",
		`{"user_id":"`+memberID+`","role_id":"`+projectManagerRoleID+`"}`,
		adminAccessToken,
	)
	if addProjectMemberResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected add project member status: %d body=%s", addProjectMemberResp.StatusCode, readBodyString(t, addProjectMemberResp))
	}

	projectPermissionsBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/resource?resource_type=project&resource_id="+projectID,
		"",
		memberAccessToken,
	))
	projectRole, ok := projectPermissionsBody["resource_role"].(map[string]any)
	if !ok || projectRole["name"] != "project_manager" {
		t.Fatalf("unexpected project resource permissions body: %+v", projectPermissionsBody)
	}
	projectPermissions, ok := projectPermissionsBody["permissions"].([]any)
	if !ok || !slices.Contains(projectPermissions, any("project:assign:assigned")) {
		t.Fatalf("expected project manager permissions, got %+v", projectPermissionsBody)
	}
	forbiddenProjectMembersResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/projects/"+otherProjectID+"/members",
		"",
		memberAccessToken,
	)
	if forbiddenProjectMembersResp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected project membership scope isolation, got %d body=%s", forbiddenProjectMembersResp.StatusCode, readBodyString(t, forbiddenProjectMembersResp))
	}
	updateDatasetMemberResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPut,
		httpServer.URL+"/datasets/"+datasetID+"/members/"+memberID,
		`{"role_id":"`+datasetViewerRoleID+`"}`,
		adminAccessToken,
	)
	if updateDatasetMemberResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected update dataset member status: %d body=%s", updateDatasetMemberResp.StatusCode, readBodyString(t, updateDatasetMemberResp))
	}
	updatedDatasetPermissionsBody := decodeJSONResponse(t, doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodGet,
		httpServer.URL+"/permissions/resource?resource_type=dataset&resource_id="+datasetID,
		"",
		memberAccessToken,
	))
	updatedPermissions, ok := updatedDatasetPermissionsBody["permissions"].([]any)
	if !ok || slices.Contains(updatedPermissions, any("dataset:update:assigned")) || !slices.Contains(updatedPermissions, any("dataset:read:assigned")) {
		t.Fatalf("expected dataset viewer permissions after update, got %+v", updatedDatasetPermissionsBody)
	}
	rejectOwnerAssignResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodPost,
		httpServer.URL+"/datasets/"+datasetID+"/members",
		`{"user_id":"`+memberID+`","role_id":"`+datasetOwnerRoleID+`"}`,
		adminAccessToken,
	)
	if rejectOwnerAssignResp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected owner role assignment rejection, got %d body=%s", rejectOwnerAssignResp.StatusCode, readBodyString(t, rejectOwnerAssignResp))
	}
	insertResourceMembership(t, sqlDB, adminPrincipalID, datasetOwnerRoleID, "dataset", datasetID)
	rejectOwnerDeleteResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodDelete,
		httpServer.URL+"/datasets/"+datasetID+"/members/"+adminPrincipalID,
		"",
		adminAccessToken,
	)
	if rejectOwnerDeleteResp.StatusCode != http.StatusConflict {
		t.Fatalf("expected owner membership delete rejection, got %d body=%s", rejectOwnerDeleteResp.StatusCode, readBodyString(t, rejectOwnerDeleteResp))
	}

	removeDatasetMemberResp := doJSONRequest(
		t,
		httpServer.Client(),
		http.MethodDelete,
		httpServer.URL+"/datasets/"+datasetID+"/members/"+memberID,
		"",
		adminAccessToken,
	)
	if removeDatasetMemberResp.StatusCode != http.StatusNoContent {
		t.Fatalf("unexpected remove dataset member status: %d body=%s", removeDatasetMemberResp.StatusCode, readBodyString(t, removeDatasetMemberResp))
	}
}

func lookupRoleIDByName(t *testing.T, sqlDB *sql.DB, name string) string {
	t.Helper()

	var roleID string
	if err := sqlDB.QueryRow(`select id::text from authz_role where name = $1`, name).Scan(&roleID); err != nil {
		t.Fatalf("lookup role %s: %v", name, err)
	}
	return roleID
}

func insertResourceMembership(t *testing.T, sqlDB *sql.DB, principalID string, roleID string, resourceType string, resourceID string) {
	t.Helper()

	if _, err := sqlDB.Exec(`
insert into authz_resource_membership (principal_id, role_id, resource_type, resource_id)
values ($1::uuid, $2::uuid, $3, $4::uuid)
on conflict (resource_type, resource_id, principal_id) do update
set role_id = excluded.role_id,
    updated_at = now()
`, principalID, roleID, resourceType, resourceID); err != nil {
		t.Fatalf("insert resource membership: %v", err)
	}
}
