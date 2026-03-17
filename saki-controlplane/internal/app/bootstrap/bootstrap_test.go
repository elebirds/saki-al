package bootstrap

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
	"slices"
	"strings"
	"testing"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestNewPublicAPISeedsAccessBeforeHandler(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startBootstrapPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, bootstrapMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")
	t.Setenv("AUTH_BOOTSTRAP_PRINCIPALS", `[{"user_id":"seed-user","display_name":"Seed User","permissions":["projects:read","imports:read"]}]`)

	server, _, err := NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	req := httptest.NewRequest(http.MethodPost, "/auth/login", bytes.NewBufferString(`{"user_id":"seed-user"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	server.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected login status: %d body=%s", rec.Code, rec.Body.String())
	}

	var body struct {
		Token       string   `json:"token"`
		UserID      string   `json:"user_id"`
		Permissions []string `json:"permissions"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode login response: %v", err)
	}
	if body.Token == "" || body.UserID != "seed-user" {
		t.Fatalf("unexpected login response: %+v", body)
	}
	if !slices.Equal(body.Permissions, []string{"imports:read", "projects:read"}) {
		t.Fatalf("unexpected login permissions: %+v", body)
	}
}

func startBootstrapPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		bootstrapPostgresImageRef(),
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

func bootstrapMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "db", "migrations")
}

func bootstrapPostgresImageRef() string {
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
