package apihttp_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	appbootstrap "github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestCreateListAndGetProjectEndpoints(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	createReq := httptest.NewRequest(http.MethodPost, "/projects", bytes.NewBufferString(`{"name":"alpha"}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)

	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ID == "" || created.Name != "alpha" {
		t.Fatalf("unexpected created project: %+v", created)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/projects", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)

	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed []map[string]any
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listed) != 1 || listed[0]["id"] != created.ID {
		t.Fatalf("unexpected listed projects: %+v", listed)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/projects/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	handler.ServeHTTP(getRec, getReq)

	if getRec.Code != http.StatusOK {
		t.Fatalf("unexpected get status: %d body=%s", getRec.Code, getRec.Body.String())
	}

	var loaded map[string]any
	if err := json.Unmarshal(getRec.Body.Bytes(), &loaded); err != nil {
		t.Fatalf("decode get response: %v", err)
	}
	if loaded["id"] != created.ID || loaded["name"] != "alpha" {
		t.Fatalf("unexpected loaded project: %+v", loaded)
	}
}

func TestProjectPersistsAcrossPublicAPIInstances(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, migrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", freeAddr(t))

	firstServer, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new first public api: %v", err)
	}

	createReq := httptest.NewRequest(http.MethodPost, "/projects", bytes.NewBufferString(`{"name":"persisted"}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	firstServer.Handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}

	secondServer, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new second public api: %v", err)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/projects/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	secondServer.Handler.ServeHTTP(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("expected persisted project on second server, got status=%d body=%s", getRec.Code, getRec.Body.String())
	}
}

func TestProjectDatasetEndpointsLinkListDetailAndUnlink(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	projectID := createProjectViaAPI(t, handler, "project-datasets")
	datasetA := createDatasetViaAPI(t, handler, "dataset-a", "image")
	datasetB := createDatasetViaAPI(t, handler, "dataset-b", "image")

	linkRec := performJSONRequest(
		handler,
		http.MethodPost,
		"/projects/"+projectID+"/datasets",
		`{"dataset_ids":["`+datasetB+`","`+datasetA+`"]}`,
	)
	if linkRec.Code != http.StatusOK {
		t.Fatalf("unexpected link status: %d body=%s", linkRec.Code, linkRec.Body.String())
	}

	var linked []string
	if err := json.Unmarshal(linkRec.Body.Bytes(), &linked); err != nil {
		t.Fatalf("decode link response: %v", err)
	}
	if len(linked) != 2 || linked[0] != datasetB || linked[1] != datasetA {
		t.Fatalf("unexpected linked ids: %+v", linked)
	}

	listRec := performJSONRequest(handler, http.MethodGet, "/projects/"+projectID+"/datasets", "")
	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list ids status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed []string
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list ids response: %v", err)
	}
	if len(listed) != 2 || !containsAll(listed, datasetA, datasetB) {
		t.Fatalf("unexpected listed ids: %+v", listed)
	}

	detailRec := performJSONRequest(handler, http.MethodGet, "/projects/"+projectID+"/datasets/detail", "")
	if detailRec.Code != http.StatusOK {
		t.Fatalf("unexpected list detail status: %d body=%s", detailRec.Code, detailRec.Body.String())
	}

	var details []struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		Type string `json:"type"`
	}
	if err := json.Unmarshal(detailRec.Body.Bytes(), &details); err != nil {
		t.Fatalf("decode list detail response: %v", err)
	}
	if len(details) != 2 {
		t.Fatalf("unexpected dataset details length: %+v", details)
	}
	if !hasDatasetDetail(details, datasetA, "dataset-a", "image") || !hasDatasetDetail(details, datasetB, "dataset-b", "image") {
		t.Fatalf("unexpected dataset details: %+v", details)
	}

	unlinkRec := performJSONRequest(
		handler,
		http.MethodDelete,
		"/projects/"+projectID+"/datasets",
		`{"dataset_ids":["`+datasetA+`"]}`,
	)
	if unlinkRec.Code != http.StatusOK {
		t.Fatalf("unexpected unlink status: %d body=%s", unlinkRec.Code, unlinkRec.Body.String())
	}

	var unlinked int
	if err := json.Unmarshal(unlinkRec.Body.Bytes(), &unlinked); err != nil {
		t.Fatalf("decode unlink response: %v", err)
	}
	if unlinked != 1 {
		t.Fatalf("unexpected unlink count: %d", unlinked)
	}

	listAfterRec := performJSONRequest(handler, http.MethodGet, "/projects/"+projectID+"/datasets", "")
	if listAfterRec.Code != http.StatusOK {
		t.Fatalf("unexpected list ids after unlink status: %d body=%s", listAfterRec.Code, listAfterRec.Body.String())
	}

	var listedAfter []string
	if err := json.Unmarshal(listAfterRec.Body.Bytes(), &listedAfter); err != nil {
		t.Fatalf("decode list ids after unlink response: %v", err)
	}
	if len(listedAfter) != 1 || listedAfter[0] != datasetB {
		t.Fatalf("unexpected listed ids after unlink: %+v", listedAfter)
	}
}

func TestProjectDatasetLinkEndpointSkipsAlreadyLinkedDatasets(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	projectID := createProjectViaAPI(t, handler, "project-datasets")
	datasetID := createDatasetViaAPI(t, handler, "dataset-a", "image")

	firstRec := performJSONRequest(
		handler,
		http.MethodPost,
		"/projects/"+projectID+"/datasets",
		`{"dataset_ids":["`+datasetID+`"]}`,
	)
	if firstRec.Code != http.StatusOK {
		t.Fatalf("unexpected first link status: %d body=%s", firstRec.Code, firstRec.Body.String())
	}

	secondRec := performJSONRequest(
		handler,
		http.MethodPost,
		"/projects/"+projectID+"/datasets",
		`{"dataset_ids":["`+datasetID+`"]}`,
	)
	if secondRec.Code != http.StatusOK {
		t.Fatalf("unexpected second link status: %d body=%s", secondRec.Code, secondRec.Body.String())
	}

	var linked []string
	if err := json.Unmarshal(secondRec.Body.Bytes(), &linked); err != nil {
		t.Fatalf("decode second link response: %v", err)
	}
	if len(linked) != 0 {
		t.Fatalf("expected no new links on second request, got %+v", linked)
	}
}

func TestProjectDatasetLinkEndpointReturns404WhenProjectOrDatasetMissing(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	projectID := createProjectViaAPI(t, handler, "project-datasets")
	datasetID := createDatasetViaAPI(t, handler, "dataset-a", "image")

	missingProjectRec := performJSONRequest(
		handler,
		http.MethodPost,
		"/projects/"+uuid.New().String()+"/datasets",
		`{"dataset_ids":["`+datasetID+`"]}`,
	)
	if missingProjectRec.Code != http.StatusNotFound {
		t.Fatalf("expected missing project 404, got %d body=%s", missingProjectRec.Code, missingProjectRec.Body.String())
	}

	missingDatasetRec := performJSONRequest(
		handler,
		http.MethodPost,
		"/projects/"+projectID+"/datasets",
		`{"dataset_ids":["`+uuid.New().String()+`"]}`,
	)
	if missingDatasetRec.Code != http.StatusNotFound {
		t.Fatalf("expected missing dataset 404, got %d body=%s", missingDatasetRec.Code, missingDatasetRec.Body.String())
	}
}

func TestProjectDatasetEndpointsRejectInvalidProjectID(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	rec := performJSONRequest(handler, http.MethodGet, "/projects/not-a-uuid/datasets", "")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid project id 400, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func newTestHTTPHandler() (http.Handler, error) {
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour),
		ClaimsStore:         fakeAccessStore{},
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
	})
}

func createProjectViaAPI(t *testing.T, handler http.Handler, name string) string {
	t.Helper()

	rec := performJSONRequest(handler, http.MethodPost, "/projects", `{"name":"`+name+`"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("unexpected create project status: %d body=%s", rec.Code, rec.Body.String())
	}

	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create project response: %v", err)
	}
	if created.ID == "" {
		t.Fatal("expected project id")
	}
	return created.ID
}

func createDatasetViaAPI(t *testing.T, handler http.Handler, name, dtype string) string {
	t.Helper()

	rec := performJSONRequest(
		handler,
		http.MethodPost,
		"/datasets",
		`{"name":"`+name+`","type":"`+dtype+`"}`,
	)
	if rec.Code != http.StatusCreated {
		t.Fatalf("unexpected create dataset status: %d body=%s", rec.Code, rec.Body.String())
	}

	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create dataset response: %v", err)
	}
	if created.ID == "" {
		t.Fatal("expected dataset id")
	}
	return created.ID
}

func performJSONRequest(handler http.Handler, method, path, body string) *httptest.ResponseRecorder {
	var reader *bytes.Reader
	if body == "" {
		reader = bytes.NewReader(nil)
	} else {
		reader = bytes.NewReader([]byte(body))
	}

	req := httptest.NewRequest(method, path, reader)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

func containsAll(ids []string, wanted ...string) bool {
	index := make(map[string]struct{}, len(ids))
	for _, id := range ids {
		index[id] = struct{}{}
	}
	for _, id := range wanted {
		if _, ok := index[id]; !ok {
			return false
		}
	}
	return true
}

func hasDatasetDetail(items []struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Type string `json:"type"`
}, id, name, dtype string) bool {
	for _, item := range items {
		if item.ID == id && item.Name == name && item.Type == dtype {
			return true
		}
	}
	return false
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

type fakeAccessStore struct{}

func (fakeAccessStore) LoadClaimsByUserID(context.Context, string) (*accessapp.ClaimsSnapshot, error) {
	return nil, nil
}

func (fakeAccessStore) LoadClaimsByPrincipalID(context.Context, uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	return nil, nil
}

func freeAddr(t *testing.T) string {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen free addr: %v", err)
	}
	defer ln.Close()
	return ln.Addr().String()
}

func startPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		postgresImageRef(),
		postgres.WithDatabase("saki"),
		postgres.WithUsername("postgres"),
		postgres.WithPassword("postgres"),
		testcontainers.WithWaitStrategy(
			wait.ForLog("database system is ready to accept connections").WithOccurrence(2),
		),
	)
	if err != nil {
		t.Fatalf("start postgres container: %v", err)
	}

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		t.Fatalf("build postgres dsn: %v", err)
	}

	return container, dsn
}

func migrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func postgresImageRef() string {
	cmd := exec.Command("docker", "image", "inspect", "postgres:16-alpine", "--format", "{{.Id}}")
	output, err := cmd.Output()
	if err != nil {
		return "postgres:16-alpine"
	}

	imageID := strings.TrimSpace(string(output))
	if imageID == "" {
		return "postgres:16-alpine"
	}
	return imageID
}
