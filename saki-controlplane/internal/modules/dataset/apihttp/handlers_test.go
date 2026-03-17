package apihttp_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	appbootstrap "github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	datasetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/apihttp"
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

func TestCreateListGetUpdateDeleteDatasetEndpoints(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	createReq := httptest.NewRequest(http.MethodPost, "/datasets", bytes.NewBufferString(`{"name":" dataset-a ","type":" image "}`))
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		Type string `json:"type"`
	}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ID == "" || created.Name != "dataset-a" || created.Type != "image" {
		t.Fatalf("unexpected created dataset: %+v", created)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/datasets", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed struct {
		Items   []map[string]any `json:"items"`
		Total   int              `json:"total"`
		Offset  int              `json:"offset"`
		Limit   int              `json:"limit"`
		Size    int              `json:"size"`
		HasMore bool             `json:"has_more"`
	}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if listed.Total != 1 || listed.Offset != 0 || listed.Limit != 20 || listed.Size != 1 || listed.HasMore {
		t.Fatalf("unexpected list envelope: %+v", listed)
	}
	if len(listed.Items) != 1 || listed.Items[0]["id"] != created.ID {
		t.Fatalf("unexpected listed datasets: %+v", listed.Items)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/datasets/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	handler.ServeHTTP(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("unexpected get status: %d body=%s", getRec.Code, getRec.Body.String())
	}

	var loaded map[string]any
	if err := json.Unmarshal(getRec.Body.Bytes(), &loaded); err != nil {
		t.Fatalf("decode get response: %v", err)
	}
	if loaded["id"] != created.ID || loaded["name"] != "dataset-a" || loaded["type"] != "image" {
		t.Fatalf("unexpected loaded dataset: %+v", loaded)
	}

	updateReq := httptest.NewRequest(http.MethodPut, "/datasets/"+created.ID, bytes.NewBufferString(`{"name":" dataset-b ","type":" lidar "}`))
	updateReq.Header.Set("Content-Type", "application/json")
	updateRec := httptest.NewRecorder()
	handler.ServeHTTP(updateRec, updateReq)
	if updateRec.Code != http.StatusOK {
		t.Fatalf("unexpected update status: %d body=%s", updateRec.Code, updateRec.Body.String())
	}

	var updated map[string]any
	if err := json.Unmarshal(updateRec.Body.Bytes(), &updated); err != nil {
		t.Fatalf("decode update response: %v", err)
	}
	if updated["id"] != created.ID || updated["name"] != "dataset-b" || updated["type"] != "lidar" {
		t.Fatalf("unexpected updated dataset: %+v", updated)
	}

	deleteReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+created.ID, nil)
	deleteRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteRec, deleteReq)
	if deleteRec.Code != http.StatusNoContent {
		t.Fatalf("unexpected delete status: %d body=%s", deleteRec.Code, deleteRec.Body.String())
	}

	deleteAgainReq := httptest.NewRequest(http.MethodDelete, "/datasets/"+created.ID, nil)
	deleteAgainRec := httptest.NewRecorder()
	handler.ServeHTTP(deleteAgainRec, deleteAgainReq)
	if deleteAgainRec.Code != http.StatusNotFound {
		t.Fatalf("expected second delete to return 404, got status=%d body=%s", deleteAgainRec.Code, deleteAgainRec.Body.String())
	}

	getDeletedReq := httptest.NewRequest(http.MethodGet, "/datasets/"+created.ID, nil)
	getDeletedRec := httptest.NewRecorder()
	handler.ServeHTTP(getDeletedRec, getDeletedReq)
	if getDeletedRec.Code != http.StatusNotFound {
		t.Fatalf("expected deleted dataset to return 404, got status=%d body=%s", getDeletedRec.Code, getDeletedRec.Body.String())
	}
}

func TestListDatasetsSupportsPageLimitAndQuery(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	for _, body := range []string{
		`{"name":"alpha","type":"image"}`,
		`{"name":"beta","type":"image"}`,
		`{"name":"alpine","type":"image"}`,
	} {
		req := httptest.NewRequest(http.MethodPost, "/datasets", bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("seed dataset failed: status=%d body=%s", rec.Code, rec.Body.String())
		}
	}

	listReq := httptest.NewRequest(http.MethodGet, "/datasets?page=2&limit=1&q=%20alp%20", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed struct {
		Items   []map[string]any `json:"items"`
		Total   int              `json:"total"`
		Offset  int              `json:"offset"`
		Limit   int              `json:"limit"`
		Size    int              `json:"size"`
		HasMore bool             `json:"has_more"`
	}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if listed.Total != 2 || listed.Offset != 1 || listed.Limit != 1 || listed.Size != 1 || listed.HasMore {
		t.Fatalf("unexpected list envelope: %+v", listed)
	}
	if len(listed.Items) != 1 || listed.Items[0]["name"] != "alpine" {
		t.Fatalf("unexpected filtered datasets: %+v", listed.Items)
	}
}

func TestDatasetPersistsAcrossPublicAPIInstances(t *testing.T) {
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
	t.Cleanup(func() {
		_ = firstServer.Shutdown(context.Background())
	})

	createReq := httptest.NewRequest(http.MethodPost, "/datasets", bytes.NewBufferString(`{"name":"persisted-dataset","type":"image"}`))
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
	if created.ID == "" {
		t.Fatalf("expected dataset id in create response: body=%s", createRec.Body.String())
	}

	secondServer, _, err := appbootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new second public api: %v", err)
	}
	t.Cleanup(func() {
		_ = secondServer.Shutdown(context.Background())
	})

	getReq := httptest.NewRequest(http.MethodGet, "/datasets/"+created.ID, nil)
	getRec := httptest.NewRecorder()
	secondServer.Handler.ServeHTTP(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("expected persisted dataset on second server, got status=%d body=%s", getRec.Code, getRec.Body.String())
	}
}

func TestGetDatasetRejectsInvalidDatasetID(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/datasets/not-a-uuid", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid dataset_id to return 400, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteDatasetRejectsInvalidDatasetID(t *testing.T) {
	handler, err := newTestHTTPHandler()
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	req := httptest.NewRequest(http.MethodDelete, "/datasets/not-a-uuid", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid dataset_id to return 400, got status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteDatasetDoesNotRequirePreGet(t *testing.T) {
	handler := datasetapi.NewHandlers(deleteOnlyStore{
		deleteResult: true,
	})

	res, err := handler.DeleteDataset(context.Background(), openapi.DeleteDatasetParams{
		DatasetID: uuid.NewString(),
	})
	if err != nil {
		t.Fatalf("delete dataset: %v", err)
	}
	if _, ok := res.(*openapi.DeleteDatasetNoContent); !ok {
		t.Fatalf("expected no-content delete response, got %T", res)
	}
}

func TestDeleteDatasetReturnsNotFoundWhenDeleteReportsNoRows(t *testing.T) {
	handler := datasetapi.NewHandlers(deleteOnlyStore{
		deleteResult: false,
	})

	res, err := handler.DeleteDataset(context.Background(), openapi.DeleteDatasetParams{
		DatasetID: uuid.NewString(),
	})
	if err != nil {
		t.Fatalf("delete dataset: %v", err)
	}
	if _, ok := res.(*openapi.DeleteDatasetNotFound); !ok {
		t.Fatalf("expected not-found delete response, got %T", res)
	}
}

func newTestHTTPHandler() (http.Handler, error) {
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour),
		AccessStore:         fakeAccessStore{},
		DatasetStore:        datasetapp.NewMemoryStore(),
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
		AnnotationDatasets:  fakeAnnotationDatasetStore{},
		AnnotationStore:     fakeAnnotationStore{},
	})
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

func (fakeAccessStore) GetPrincipalByUserID(context.Context, string) (*accessdomain.Principal, error) {
	return nil, nil
}

func (fakeAccessStore) GetPrincipalByID(context.Context, uuid.UUID) (*accessdomain.Principal, error) {
	return nil, nil
}

func (fakeAccessStore) ListPermissions(context.Context, uuid.UUID) ([]string, error) {
	return nil, nil
}

func (fakeAccessStore) UpsertBootstrapPrincipal(context.Context, accessapp.BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	return nil, nil
}

type deleteOnlyStore struct {
	deleteResult bool
}

func (deleteOnlyStore) Create(context.Context, datasetrepo.CreateDatasetParams) (*datasetrepo.Dataset, error) {
	return nil, nil
}

func (deleteOnlyStore) Get(context.Context, uuid.UUID) (*datasetrepo.Dataset, error) {
	return nil, errors.New("Get should not be called")
}

func (deleteOnlyStore) List(context.Context, datasetrepo.ListDatasetsParams) (*datasetrepo.DatasetPage, error) {
	return nil, nil
}

func (deleteOnlyStore) Update(context.Context, datasetrepo.UpdateDatasetParams) (*datasetrepo.Dataset, error) {
	return nil, nil
}

func (s deleteOnlyStore) Delete(context.Context, uuid.UUID) (bool, error) {
	return s.deleteResult, nil
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
