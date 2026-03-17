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
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
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

func newTestHTTPHandler() (http.Handler, error) {
	return systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour),
		AccessStore:         fakeAccessStore{},
		ProjectStore:        projectapp.NewMemoryStore(),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   fakeAnnotationSampleStore{},
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

type fakeAnnotationStore struct{}

func (fakeAnnotationStore) Create(context.Context, annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error) {
	return nil, nil
}

func (fakeAnnotationStore) ListBySample(context.Context, uuid.UUID) ([]annotationrepo.Annotation, error) {
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
