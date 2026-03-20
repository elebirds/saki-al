package apihttp_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
	"net/http"
	"net/http/httptest"
)

func TestCreateAndListSampleAnnotationsEndpoints(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAnnotationPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	pool := openAnnotationPool(t, ctx, dsn)
	defer pool.Close()

	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	projectRepo := projectrepo.NewProjectRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	project, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "demo-project"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}
	dataset, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{Name: "demo-dataset", Type: "fedo-dual-view"})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}
	if _, err := projectRepo.LinkDataset(ctx, project.ID, dataset.ID); err != nil {
		t.Fatalf("link dataset: %v", err)
	}
	sample, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: dataset.ID,
		Name:      "sample-1",
		Meta:      []byte(`{"source_view":"rgb","target_view":"thermal","lookup_ref":"lut-1"}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator:       accessapp.NewAuthenticator("test-secret", time.Hour),
		ClaimsStore:         fakeAccessStore{},
		DatasetStore:        datasetapp.NewRepoStore(datasetRepo),
		ProjectStore:        projectapp.NewRepoStore(projectRepo),
		RuntimeStore:        runtimequeries.NewMemoryAdminStore(),
		RuntimeTaskCanceler: fakeRuntimeTaskCanceler{},
		AnnotationSamples:   sampleRepo,
		AnnotationDatasets:  datasetRepo,
		AnnotationStore:     annotationrepo.NewAnnotationRepo(pool),
	})
	if err != nil {
		t.Fatalf("new http handler: %v", err)
	}

	createReq := httptest.NewRequest(
		http.MethodPost,
		"/projects/"+project.ID.String()+"/samples/"+sample.ID.String()+"/annotations",
		bytes.NewBufferString(`{"group_id":"group-a","label_id":"car","view":"rgb","annotation_type":"obb","geometry":{"cx":10,"cy":20,"w":5,"h":6,"angle":30},"attrs":{"score":0.9},"source":"manual"}`),
	)
	createReq.Header.Set("Content-Type", "application/json")
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("unexpected create status: %d body=%s", createRec.Code, createRec.Body.String())
	}

	var created []map[string]any
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if len(created) != 1 || created[0]["sample_id"] != sample.ID.String() {
		t.Fatalf("unexpected create response: %+v", created)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/projects/"+project.ID.String()+"/samples/"+sample.ID.String()+"/annotations", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("unexpected list status: %d body=%s", listRec.Code, listRec.Body.String())
	}

	var listed []map[string]any
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if len(listed) != 1 || listed[0]["view"] != "rgb" || listed[0]["annotation_type"] != "obb" {
		t.Fatalf("unexpected list response: %+v", listed)
	}
}

type fakeRuntimeTaskCanceler struct{}

func (fakeRuntimeTaskCanceler) Handle(context.Context, runtimecommands.CancelTaskCommand) (*runtimecommands.TaskRecord, error) {
	return &runtimecommands.TaskRecord{}, nil
}

type fakeAccessStore struct{}

func (fakeAccessStore) LoadClaimsByUserID(context.Context, string) (*accessapp.ClaimsSnapshot, error) {
	return nil, nil
}

func (fakeAccessStore) LoadClaimsByPrincipalID(context.Context, uuid.UUID) (*accessapp.ClaimsSnapshot, error) {
	return nil, nil
}

func openAnnotationPool(t *testing.T, ctx context.Context, dsn string) *pgxpool.Pool {
	t.Helper()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, annotationMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	return pool
}

func startAnnotationPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		annotationPostgresImageRef(),
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

func annotationMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func annotationPostgresImageRef() string {
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
