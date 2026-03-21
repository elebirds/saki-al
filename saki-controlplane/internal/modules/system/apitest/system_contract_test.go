package apitest

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	systemopenapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	authorizationapi "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/apihttp"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	identityapi "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/apihttp"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
	"github.com/go-faster/jx"
	"github.com/google/uuid"
)

func TestHumanControlPlaneSystemStatusContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{
		status: &fakeStatusExecutor{
			status: &systemapp.Status{
				InstallState:      systemdomain.InstallationStateUninitialized,
				AllowSelfRegister: false,
				Version:           "test-build",
			},
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/system/status", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode status body: %v", err)
	}
	if body["install_state"] != "uninitialized" || body["allow_self_register"] != false || body["version"] != "test-build" {
		t.Fatalf("unexpected status body: %+v", body)
	}
}

func TestHumanControlPlaneSystemInitContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{
		initialize: &fakeInitializeSystemExecutor{
			session: &systemapp.AuthSession{
				AccessToken:        "access-token",
				RefreshToken:       "refresh-token",
				ExpiresIn:          600,
				MustChangePassword: false,
				User: systemapp.SessionUser{
					PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000001401"),
					Email:       "admin@example.com",
					FullName:    "Initial Admin",
				},
			},
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/system/init", bytes.NewBufferString(`{"email":"admin@example.com","password":"secret","full_name":"Initial Admin"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode init body: %v", err)
	}
	if body["access_token"] != "access-token" || body["refresh_token"] != "refresh-token" {
		t.Fatalf("unexpected init tokens: %+v", body)
	}
}

func TestHumanControlPlaneRemovedSystemSetupEndpointReturns404(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})

	req := httptest.NewRequest(http.MethodPost, "/system/setup", bytes.NewBufferString(`{"email":"admin@example.com","password":"secret","full_name":"Initial Admin"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneRemovedSystemSetupEndpointReturns404WithInvalidBearer(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})

	req := httptest.NewRequest(http.MethodPost, "/system/setup", bytes.NewBufferString(`{"email":"admin@example.com","password":"secret","full_name":"Initial Admin"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer definitely-invalid")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneSystemSettingsRequireAuth(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})

	req := httptest.NewRequest(http.MethodGet, "/system/settings", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected unauthorized, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneSystemTypesContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})

	req := httptest.NewRequest(http.MethodGet, "/system/types", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode types body: %v", err)
	}
	taskTypes, ok := body["task_types"].([]any)
	if !ok || len(taskTypes) == 0 {
		t.Fatalf("unexpected task types body: %+v", body)
	}
	datasetTypes, ok := body["dataset_types"].([]any)
	if !ok || len(datasetTypes) == 0 {
		t.Fatalf("unexpected dataset types body: %+v", body)
	}
}

func TestHumanControlPlaneSystemSettingsGetContract(t *testing.T) {
	settings := &fakeSettingsManager{
		bundle: &systemapp.SettingsBundle{
			Schema: []systemapp.SettingDefinition{
				{
					Key:         systemapp.SettingKeyAuthAllowSelfRegister,
					Group:       "auth",
					Title:       "Allow self register",
					Description: "desc",
					Type:        "boolean",
					Default:     json.RawMessage(`false`),
					Editable:    true,
				},
			},
			Values: map[string]json.RawMessage{
				systemapp.SettingKeyAuthAllowSelfRegister: json.RawMessage(`true`),
			},
		},
	}
	handler := newSystemHTTPHandler(t, contractDeps{settings: settings})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/system/settings", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode settings body: %v", err)
	}
	values, ok := body["values"].(map[string]any)
	if !ok {
		t.Fatalf("unexpected settings values body: %+v", body)
	}
	value, ok := values[systemapp.SettingKeyAuthAllowSelfRegister].(map[string]any)
	if !ok || value["kind"] != "boolean" || value["bool_value"] != true {
		t.Fatalf("unexpected settings value: %+v", body)
	}
}

func TestHumanControlPlaneSystemSettingsRejectsLegacyPermissionAlias(t *testing.T) {
	settings := &fakeSettingsManager{
		bundle: &systemapp.SettingsBundle{
			Schema: []systemapp.SettingDefinition{
				{
					Key:         systemapp.SettingKeyAuthAllowSelfRegister,
					Group:       "auth",
					Title:       "Allow self register",
					Description: "desc",
					Type:        "boolean",
					Default:     json.RawMessage(`false`),
					Editable:    true,
				},
			},
			Values: map[string]json.RawMessage{
				systemapp.SettingKeyAuthAllowSelfRegister: json.RawMessage(`true`),
			},
		},
	}
	handler := newSystemHTTPHandler(t, contractDeps{
		settings:    settings,
		permissions: []string{"system_setting:read"},
	})
	token := issueSystemTokenWithPermissions(t, "admin@example.com", []string{"system_setting:read"})

	req := httptest.NewRequest(http.MethodGet, "/system/settings", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneSystemSettingsPatchContract(t *testing.T) {
	settings := &fakeSettingsManager{
		bundle: &systemapp.SettingsBundle{
			Schema: []systemapp.SettingDefinition{
				{
					Key:         systemapp.SettingKeyAuthAllowSelfRegister,
					Group:       "auth",
					Title:       "Allow self register",
					Description: "desc",
					Type:        "boolean",
					Default:     json.RawMessage(`false`),
					Editable:    true,
				},
			},
			Values: map[string]json.RawMessage{
				systemapp.SettingKeyAuthAllowSelfRegister: json.RawMessage(`true`),
			},
		},
	}
	handler := newSystemHTTPHandler(t, contractDeps{settings: settings})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodPatch, "/system/settings", bytes.NewBufferString(`{"values":{"auth.allow_self_register":{"kind":"boolean","bool_value":true}}}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected patch status code: %d body=%s", rec.Code, rec.Body.String())
	}
	if got := string(settings.patchValues[systemapp.SettingKeyAuthAllowSelfRegister]); got != "true" {
		t.Fatalf("unexpected patch payload: %+v", settings.patchValues)
	}
}

func TestHumanControlPlaneSystemSettingsPatchRejectsKindMismatch(t *testing.T) {
	settings := &fakeSettingsManager{
		bundle: &systemapp.SettingsBundle{
			Schema: []systemapp.SettingDefinition{
				{
					Key:         systemapp.SettingKeyAuthAllowSelfRegister,
					Group:       "auth",
					Title:       "Allow self register",
					Description: "desc",
					Type:        "boolean",
					Default:     json.RawMessage(`false`),
					Editable:    true,
				},
			},
			Values: map[string]json.RawMessage{
				systemapp.SettingKeyAuthAllowSelfRegister: json.RawMessage(`false`),
			},
		},
	}
	handler := newSystemHTTPHandler(t, contractDeps{settings: settings})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodPatch, "/system/settings", bytes.NewBufferString(`{"values":{"auth.allow_self_register":{"kind":"string","bool_value":true}}}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected bad request, got %d body=%s", rec.Code, rec.Body.String())
	}
	if settings.patchValues != nil {
		t.Fatalf("expected rejected payload not to reach settings manager, got %+v", settings.patchValues)
	}
}

func TestHumanControlPlaneLoginRejectsLegacyBootstrapPayload(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewBufferString(`{"user_id":"seed-user"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHumanControlPlaneAuthMeReturnsCanonicalPermissions(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{})
	token := issueSystemToken(t, handler, "admin@example.com")

	req := httptest.NewRequest(http.MethodGet, "/auth/me", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode auth me body: %v", err)
	}
	if _, ok := body["user_id"]; ok {
		t.Fatalf("latest auth me should not expose legacy user_id field, got %+v", body)
	}
	permissions, ok := body["permissions"].([]any)
	if !ok {
		t.Fatalf("expected permissions array, got %+v", body)
	}
	for _, permission := range []string{"system:read", "system:write", "users:read", "roles:read"} {
		if !containsAnyValue(permissions, permission) {
			t.Fatalf("expected auth me permissions to contain %q, got %+v", permission, permissions)
		}
	}
	for _, removedAlias := range []string{"user:read:all", "system_setting:read:all", "role:read:all"} {
		if containsAnyValue(permissions, removedAlias) {
			t.Fatalf("expected auth me permissions not to contain removed alias %q, got %+v", removedAlias, permissions)
		}
	}
}

type contractDeps struct {
	status       *fakeStatusExecutor
	initialize   *fakeInitializeSystemExecutor
	settings     *fakeSettingsManager
	users        *fakeListUsersExecutor
	roles        *fakeListRolesExecutor
	catalog      *fakePermissionCatalogExecutor
	bindings     *fakeUserSystemRolesExecutor
	replaceRoles *fakeReplaceUserSystemRolesExecutor
	permissions  []string
}

func newSystemHTTPHandler(t *testing.T, deps contractDeps) http.Handler {
	t.Helper()

	permissions := deps.permissions
	if len(permissions) == 0 {
		permissions = defaultContractPermissions()
	}

	claimsStore := &fakeClaimsStore{
		byUserID: map[string]*accessapp.ClaimsSnapshot{
			"admin@example.com": {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000001499"),
				UserID:      "admin@example.com",
				Permissions: append([]string(nil), permissions...),
			},
		},
		byPrincipalID: map[uuid.UUID]*accessapp.ClaimsSnapshot{},
	}
	authenticator := accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(claimsStore)
	for _, snapshot := range claimsStore.byUserID {
		copy := *snapshot
		claimsStore.byPrincipalID[copy.PrincipalID] = &copy
	}
	if deps.users == nil {
		deps.users = &fakeListUsersExecutor{}
	}
	if deps.roles == nil {
		deps.roles = &fakeListRolesExecutor{}
	}
	if deps.catalog == nil {
		deps.catalog = &fakePermissionCatalogExecutor{}
	}
	if deps.bindings == nil {
		deps.bindings = &fakeUserSystemRolesExecutor{}
	}
	if deps.replaceRoles == nil {
		deps.replaceRoles = &fakeReplaceUserSystemRolesExecutor{}
	}

	identityHandlers := identityapi.NewHandlers(identityapi.HandlersDeps{
		CurrentUser: &fakeCurrentUserExecutor{},
		ListUsers:   deps.users,
	})
	authorizationHandlers := authorizationapi.NewHandlers(authorizationapi.HandlersDeps{
		ListRoles:         deps.roles,
		PermissionCatalog: deps.catalog,
		UserSystemRoles:   deps.bindings,
		ReplaceUserRoles:  deps.replaceRoles,
	})
	systemHandlers := systemapi.NewHandlers(systemapi.HandlersDeps{
		Status:     deps.status,
		Types:      &fakeTypesExecutor{},
		Initialize: deps.initialize,
		Settings:   deps.settings,
	})

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       authenticator,
		ClaimsStore:         claimsStore,
		Identity:            identityHandlers,
		Authorization:       authorizationHandlers,
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
		System:              systemHandlers,
	})
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}
	return handler
}

func issueSystemToken(t *testing.T, _ http.Handler, userID string) string {
	t.Helper()

	return issueSystemTokenWithPermissions(t, userID, defaultContractPermissions())
}

func issueSystemTokenWithPermissions(t *testing.T, userID string, permissions []string) string {
	t.Helper()

	store := &fakeClaimsStore{
		byUserID: map[string]*accessapp.ClaimsSnapshot{
			userID: {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000001499"),
				UserID:      userID,
				Permissions: append([]string(nil), permissions...),
			},
		},
		byPrincipalID: map[uuid.UUID]*accessapp.ClaimsSnapshot{},
	}
	for _, snapshot := range store.byUserID {
		copy := *snapshot
		store.byPrincipalID[copy.PrincipalID] = &copy
	}

	token, err := accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(store).IssueTokenContext(context.Background(), userID)
	if err != nil {
		t.Fatalf("issue token: %v", err)
	}
	return token
}

func defaultContractPermissions() []string {
	return []string{"system:read", "system:write", "users:read", "roles:read"}
}

type fakeClaimsStore struct {
	byUserID      map[string]*accessapp.ClaimsSnapshot
	byPrincipalID map[uuid.UUID]*accessapp.ClaimsSnapshot
}

func (f *fakeClaimsStore) LoadClaimsByUserID(_ context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	if f.byPrincipalID == nil {
		f.byPrincipalID = map[uuid.UUID]*accessapp.ClaimsSnapshot{}
	}
	snapshot := f.byUserID[userID]
	if snapshot == nil {
		return nil, nil
	}
	copy := *snapshot
	copy.Permissions = append([]string(nil), snapshot.Permissions...)
	return &copy, nil
}

func (f *fakeClaimsStore) LoadClaimsByPrincipalID(_ context.Context, principalID uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	if f.byPrincipalID == nil {
		f.byPrincipalID = map[uuid.UUID]*accessapp.ClaimsSnapshot{}
	}
	snapshot := f.byPrincipalID[principalID]
	if snapshot == nil {
		return nil, nil
	}
	copy := *snapshot
	copy.Permissions = append([]string(nil), snapshot.Permissions...)
	return &copy, nil
}

func containsAnyValue(items []any, target string) bool {
	for _, item := range items {
		if item == target {
			return true
		}
	}
	return false
}

type fakeCurrentUserExecutor struct{}

func (fakeCurrentUserExecutor) Execute(_ context.Context, principalID uuid.UUID, permissions []string) (*identityapp.CurrentUser, error) {
	return &identityapp.CurrentUser{
		User: identityapp.SessionUser{
			PrincipalID: principalID,
			Email:       "admin@example.com",
			FullName:    "Admin User",
		},
		SystemRoles:        []string{"super_admin"},
		Permissions:        append([]string(nil), permissions...),
		MustChangePassword: false,
	}, nil
}

type fakeListUsersExecutor struct {
	result *identityapp.ListUsersResult
}

func (f *fakeListUsersExecutor) Execute(context.Context, identityapp.ListUsersInput) (*identityapp.ListUsersResult, error) {
	if f == nil || f.result == nil {
		return &identityapp.ListUsersResult{
			Items: []identityapp.UserAdminView{
				{
					ID:                 "00000000-0000-0000-0000-000000001499",
					Email:              "admin@example.com",
					FullName:           "Admin User",
					IsActive:           true,
					MustChangePassword: false,
					CreatedAt:          time.Date(2026, 3, 20, 1, 2, 3, 0, time.UTC),
					UpdatedAt:          time.Date(2026, 3, 20, 1, 2, 3, 0, time.UTC),
					Roles: []identityapp.UserRoleSummary{
						{
							ID:          "00000000-0000-0000-0000-000000001501",
							Name:        "super_admin",
							DisplayName: "Super Admin",
							Color:       "red",
							IsSupremo:   true,
						},
					},
				},
			},
			Total:   1,
			Offset:  0,
			Limit:   20,
			Size:    1,
			HasMore: false,
		}, nil
	}
	copy := *f.result
	return &copy, nil
}

type fakeListRolesExecutor struct {
	result *authorizationapp.RoleListResult
}

func (f *fakeListRolesExecutor) Execute(context.Context, authorizationapp.ListRolesInput) (*authorizationapp.RoleListResult, error) {
	if f == nil || f.result == nil {
		return &authorizationapp.RoleListResult{
			Items: []authorizationapp.RoleView{
				{
					ID:          "00000000-0000-0000-0000-000000001501",
					Name:        "super_admin",
					DisplayName: "Super Admin",
					Description: "Builtin super admin role",
					Type:        "system",
					BuiltIn:     true,
					Mutable:     false,
					Color:       "red",
					IsSupremo:   true,
					SortOrder:   0,
					IsSystem:    true,
					Permissions: []authorizationapp.RolePermissionView{
						{Permission: "roles:read"},
						{Permission: "users:read"},
					},
					CreatedAt: time.Date(2026, 3, 20, 1, 2, 3, 0, time.UTC),
					UpdatedAt: time.Date(2026, 3, 20, 1, 2, 3, 0, time.UTC),
				},
			},
			Total:   1,
			Offset:  0,
			Limit:   20,
			Size:    1,
			HasMore: false,
		}, nil
	}
	copy := *f.result
	return &copy, nil
}

type fakePermissionCatalogExecutor struct {
	result *authorizationapp.PermissionCatalog
}

func (f *fakePermissionCatalogExecutor) Execute(context.Context) (*authorizationapp.PermissionCatalog, error) {
	if f == nil || f.result == nil {
		return &authorizationapp.PermissionCatalog{
			AllPermissions:      []string{"roles:read", "system:write", "users:read"},
			SystemPermissions:   []string{"roles:read", "system:write", "users:read"},
			ResourcePermissions: []string{"projects:read", "projects:write"},
			ResourceRoles: []authorizationapp.ResourceRoleDefinitionView{
				{
					ResourceType: "project",
					Name:         "project_manager",
					DisplayName:  "Project Manager",
					Description:  "Can manage project workflows and membership.",
					Color:        "cyan",
					SortOrder:    10,
					IsSupremo:    false,
					Assignable:   true,
					Permissions:  []string{"projects:read", "projects:write"},
				},
			},
		}, nil
	}
	copy := *f.result
	return &copy, nil
}

type fakeUserSystemRolesExecutor struct {
	result []authorizationapp.UserSystemRoleBindingView
}

func (f *fakeUserSystemRolesExecutor) Execute(context.Context, uuid.UUID) ([]authorizationapp.UserSystemRoleBindingView, error) {
	if f == nil || f.result == nil {
		return []authorizationapp.UserSystemRoleBindingView{
			{
				ID:              "00000000-0000-0000-0000-000000001601",
				PrincipalID:     "00000000-0000-0000-0000-000000001499",
				RoleID:          "00000000-0000-0000-0000-000000001501",
				RoleName:        "super_admin",
				RoleDisplayName: "Super Admin",
				AssignedAt:      time.Date(2026, 3, 20, 1, 2, 3, 0, time.UTC),
			},
		}, nil
	}
	return append([]authorizationapp.UserSystemRoleBindingView(nil), f.result...), nil
}

type fakeReplaceUserSystemRolesExecutor struct {
	result []authorizationapp.UserSystemRoleBindingView
}

func (f *fakeReplaceUserSystemRolesExecutor) Execute(context.Context, authorizationapp.ReplaceUserSystemRolesCommand) ([]authorizationapp.UserSystemRoleBindingView, error) {
	if f == nil || f.result == nil {
		return []authorizationapp.UserSystemRoleBindingView{
			{
				ID:              "00000000-0000-0000-0000-000000001701",
				PrincipalID:     "00000000-0000-0000-0000-000000001500",
				RoleID:          "00000000-0000-0000-0000-000000001501",
				RoleName:        "super_admin",
				RoleDisplayName: "Super Admin",
				AssignedAt:      time.Date(2026, 3, 20, 1, 2, 3, 0, time.UTC),
			},
		}, nil
	}
	return append([]authorizationapp.UserSystemRoleBindingView(nil), f.result...), nil
}

type fakeStatusExecutor struct {
	status *systemapp.Status
}

func (f *fakeStatusExecutor) Execute(context.Context) (*systemapp.Status, error) {
	if f == nil || f.status == nil {
		return &systemapp.Status{}, nil
	}
	copy := *f.status
	return &copy, nil
}

type fakeTypesExecutor struct{}

func (fakeTypesExecutor) Execute(context.Context) (*systemapp.TypesCatalog, error) {
	return &systemapp.TypesCatalog{
		TaskTypes:    []systemapp.TypeInfo{{Value: "detection", Label: "Detection", Enabled: true}},
		DatasetTypes: []systemapp.TypeInfo{{Value: "classic", Label: "Classic", Enabled: true}},
	}, nil
}

type fakeInitializeSystemExecutor struct {
	session *systemapp.AuthSession
}

func (f *fakeInitializeSystemExecutor) Execute(context.Context, systemapp.InitializeSystemCommand) (*systemapp.AuthSession, error) {
	if f == nil || f.session == nil {
		return nil, nil
	}
	copy := *f.session
	return &copy, nil
}

type fakeSettingsManager struct {
	bundle      *systemapp.SettingsBundle
	patchValues map[string]json.RawMessage
}

func (f *fakeSettingsManager) GetBundle(context.Context) (*systemapp.SettingsBundle, error) {
	if f == nil || f.bundle == nil {
		return &systemapp.SettingsBundle{}, nil
	}
	return cloneSettingsBundle(f.bundle), nil
}

func (f *fakeSettingsManager) Patch(_ context.Context, values map[string]json.RawMessage) (*systemapp.SettingsBundle, error) {
	f.patchValues = cloneRawMap(values)
	if f.bundle == nil {
		f.bundle = &systemapp.SettingsBundle{}
	}
	if f.bundle.Values == nil {
		f.bundle.Values = map[string]json.RawMessage{}
	}
	for key, value := range values {
		f.bundle.Values[key] = append(json.RawMessage(nil), value...)
	}
	return cloneSettingsBundle(f.bundle), nil
}

func cloneSettingsBundle(bundle *systemapp.SettingsBundle) *systemapp.SettingsBundle {
	if bundle == nil {
		return nil
	}
	copy := &systemapp.SettingsBundle{
		Schema: append([]systemapp.SettingDefinition(nil), bundle.Schema...),
		Values: cloneRawMap(bundle.Values),
	}
	return copy
}

func cloneRawMap(source map[string]json.RawMessage) map[string]json.RawMessage {
	if source == nil {
		return nil
	}
	cloned := make(map[string]json.RawMessage, len(source))
	for key, value := range source {
		cloned[key] = append(json.RawMessage(nil), value...)
	}
	return cloned
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

var _ = authctx.WithClaims
var _ = systemopenapi.HealthResponse{}
var _ = jx.Raw{}
