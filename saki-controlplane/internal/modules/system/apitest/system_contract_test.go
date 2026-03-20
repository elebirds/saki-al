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
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
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

func TestHumanControlPlaneSystemSetupContract(t *testing.T) {
	handler := newSystemHTTPHandler(t, contractDeps{
		setup: &fakeSetupExecutor{
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

	req := httptest.NewRequest(http.MethodPost, "/system/setup", bytes.NewBufferString(`{"email":"admin@example.com","password":"secret","full_name":"Initial Admin"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d body=%s", rec.Code, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode setup body: %v", err)
	}
	if body["access_token"] != "access-token" || body["refresh_token"] != "refresh-token" {
		t.Fatalf("unexpected setup tokens: %+v", body)
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

type contractDeps struct {
	status   *fakeStatusExecutor
	setup    *fakeSetupExecutor
	settings *fakeSettingsManager
}

func newSystemHTTPHandler(t *testing.T, deps contractDeps) http.Handler {
	t.Helper()

	claimsStore := &fakeClaimsStore{
		byUserID: map[string]*accessapp.ClaimsSnapshot{
			"admin@example.com": {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000001499"),
				UserID:      "admin@example.com",
				Permissions: []string{"system:read", "system:write"},
			},
		},
		byPrincipalID: map[uuid.UUID]*accessapp.ClaimsSnapshot{},
	}
	authenticator := accessapp.NewAuthenticator("test-secret", time.Hour).WithStore(claimsStore)
	for _, snapshot := range claimsStore.byUserID {
		copy := *snapshot
		claimsStore.byPrincipalID[copy.PrincipalID] = &copy
	}

	systemHandlers := systemapi.NewHandlers(systemapi.HandlersDeps{
		Status:   deps.status,
		Types:    &fakeTypesExecutor{},
		Setup:    deps.setup,
		Settings: deps.settings,
	})

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       authenticator,
		ClaimsStore:         claimsStore,
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

	store := &fakeClaimsStore{
		byUserID: map[string]*accessapp.ClaimsSnapshot{
			userID: {
				PrincipalID: uuid.MustParse("00000000-0000-0000-0000-000000001499"),
				UserID:      userID,
				Permissions: []string{"system:read", "system:write"},
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

func (f *fakeClaimsStore) LoadBootstrapClaimsByUserID(ctx context.Context, userID string) (*accessapp.ClaimsSnapshot, error) {
	return f.LoadClaimsByUserID(ctx, userID)
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

type fakeSetupExecutor struct {
	session *systemapp.AuthSession
}

func (f *fakeSetupExecutor) Execute(context.Context, systemapp.SetupCommand) (*systemapp.AuthSession, error) {
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
