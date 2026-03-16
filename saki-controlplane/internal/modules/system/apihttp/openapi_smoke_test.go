package apihttp_test

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	"github.com/google/uuid"
	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestPublicAPISmoke(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startSmokePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, smokeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pgx pool: %v", err)
	}
	defer pool.Close()

	sampleRepo := annotationrepo.NewSampleRepo(pool)
	sample, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		ProjectID:   uuid.MustParse("00000000-0000-0000-0000-000000000100"),
		DatasetType: "single-view",
		Meta:        []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create smoke sample: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "smoke-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")

	server, _, err := bootstrap.NewPublicAPI(context.Background())
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}

	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	resp, err := http.Get(httpServer.URL + "/healthz")
	if err != nil {
		t.Fatalf("get healthz: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected healthz status: %d", resp.StatusCode)
	}

	loginResp, err := http.Post(
		httpServer.URL+"/auth/login",
		"application/json",
		bytes.NewBufferString(`{"user_id":"smoke-user","permissions":["projects:read"]}`),
	)
	if err != nil {
		t.Fatalf("post login: %v", err)
	}
	defer loginResp.Body.Close()
	if loginResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected login status: %d", loginResp.StatusCode)
	}

	summaryResp, err := http.Get(httpServer.URL + "/runtime/summary")
	if err != nil {
		t.Fatalf("get runtime summary: %v", err)
	}
	defer summaryResp.Body.Close()
	if summaryResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected runtime summary status: %d", summaryResp.StatusCode)
	}

	var summary map[string]any
	if err := json.NewDecoder(summaryResp.Body).Decode(&summary); err != nil {
		t.Fatalf("decode runtime summary: %v", err)
	}
	if _, ok := summary["pending_tasks"]; !ok {
		t.Fatalf("unexpected runtime summary body: %+v", summary)
	}

	createAnnotationResp, err := http.Post(
		httpServer.URL+"/samples/"+sample.ID.String()+"/annotations",
		"application/json",
		bytes.NewBufferString(`{"group_id":"smoke-group","label_id":"smoke-label","view":"rgb","annotation_type":"rect","geometry":{"x":1,"y":2,"w":3,"h":4},"attrs":{"score":0.5},"source":"manual"}`),
	)
	if err != nil {
		t.Fatalf("post sample annotations: %v", err)
	}
	defer createAnnotationResp.Body.Close()
	if createAnnotationResp.StatusCode != http.StatusCreated {
		t.Fatalf("unexpected create annotation status: %d", createAnnotationResp.StatusCode)
	}

	var created []map[string]any
	if err := json.NewDecoder(createAnnotationResp.Body).Decode(&created); err != nil {
		t.Fatalf("decode create annotation response: %v", err)
	}
	if len(created) != 1 || created[0]["sample_id"] != sample.ID.String() {
		t.Fatalf("unexpected create annotation body: %+v", created)
	}

	listAnnotationResp, err := http.Get(httpServer.URL + "/samples/" + sample.ID.String() + "/annotations")
	if err != nil {
		t.Fatalf("get sample annotations: %v", err)
	}
	defer listAnnotationResp.Body.Close()
	if listAnnotationResp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected list annotation status: %d", listAnnotationResp.StatusCode)
	}

	var listed []map[string]any
	if err := json.NewDecoder(listAnnotationResp.Body).Decode(&listed); err != nil {
		t.Fatalf("decode list annotation response: %v", err)
	}
	if len(listed) != 1 || listed[0]["view"] != "rgb" || listed[0]["annotation_type"] != "rect" {
		t.Fatalf("unexpected list annotation body: %+v", listed)
	}
}

func startSmokePostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		smokePostgresImageRef(),
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

func smokeMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func smokePostgresImageRef() string {
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
