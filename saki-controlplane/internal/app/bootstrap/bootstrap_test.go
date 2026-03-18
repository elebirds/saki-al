package bootstrap

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
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
	t.Setenv("MINIO_ENDPOINT", "127.0.0.1:9000")
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "false")
	restoreProviderFactory := overrideObjectProviderFactoryForTest(func(storage.Config) (storage.Provider, error) {
		return &fakeBootstrapProvider{}, nil
	})
	defer restoreProviderFactory()

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

func TestPublicAPIBootstrapStartsAndStopsAssetCleaner(t *testing.T) {
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
	t.Setenv("AUTH_BOOTSTRAP_PRINCIPALS", `[]`)
	t.Setenv("MINIO_ENDPOINT", "127.0.0.1:9000")
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "false")

	restoreProviderFactory := overrideObjectProviderFactoryForTest(func(storage.Config) (storage.Provider, error) {
		return &fakeBootstrapProvider{}, nil
	})
	defer restoreProviderFactory()

	started := make(chan struct{}, 1)
	stopped := make(chan struct{}, 1)
	restoreCleanerLoopFactory := overrideAssetCleanerLoopFactoryForTest(func(assetapp.StalePendingStore, assetapp.ReadyOrphanStore, assetapp.ReadyOrphanTxRunner, storage.Provider, *slog.Logger, time.Duration) backgroundLoop {
		return backgroundLoopFunc(func(ctx context.Context) error {
			select {
			case started <- struct{}{}:
			default:
			}
			<-ctx.Done()
			select {
			case stopped <- struct{}{}:
			default:
			}
			return nil
		})
	})
	defer restoreCleanerLoopFactory()

	server, _, err := NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api: %v", err)
	}

	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("asset cleaner did not start")
	}

	if err := server.Shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown server: %v", err)
	}

	select {
	case <-stopped:
	case <-time.After(2 * time.Second):
		t.Fatal("asset cleaner did not stop")
	}
}

func TestNewPublicAPIAllowsMissingObjectStorageConfig(t *testing.T) {
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
	t.Setenv("AUTH_BOOTSTRAP_PRINCIPALS", `[]`)
	t.Setenv("MINIO_ENDPOINT", "")
	t.Setenv("MINIO_ACCESS_KEY", "")
	t.Setenv("MINIO_SECRET_KEY", "")
	t.Setenv("MINIO_BUCKET_NAME", "")

	restoreProviderFactory := overrideObjectProviderFactoryForTest(func(storage.Config) (storage.Provider, error) {
		t.Fatal("object provider factory should not be called when storage config is absent")
		return nil, nil
	})
	defer restoreProviderFactory()

	cleanerStarted := false
	restoreCleanerLoopFactory := overrideAssetCleanerLoopFactoryForTest(func(assetapp.StalePendingStore, assetapp.ReadyOrphanStore, assetapp.ReadyOrphanTxRunner, storage.Provider, *slog.Logger, time.Duration) backgroundLoop {
		cleanerStarted = true
		return nil
	})
	defer restoreCleanerLoopFactory()

	server, _, err := NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("new public api without object storage: %v", err)
	}
	defer func() {
		_ = server.Shutdown(context.Background())
	}()

	if cleanerStarted {
		t.Fatal("asset cleaner should not start when object storage is disabled")
	}

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	server.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected healthz status: %d body=%s", rec.Code, rec.Body.String())
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

func overrideObjectProviderFactoryForTest(factory func(storage.Config) (storage.Provider, error)) func() {
	previous := objectProviderFactory
	objectProviderFactory = factory
	return func() {
		objectProviderFactory = previous
	}
}

func overrideAssetCleanerLoopFactoryForTest(factory func(assetapp.StalePendingStore, assetapp.ReadyOrphanStore, assetapp.ReadyOrphanTxRunner, storage.Provider, *slog.Logger, time.Duration) backgroundLoop) func() {
	previous := assetCleanerLoopFactory
	assetCleanerLoopFactory = factory
	return func() {
		assetCleanerLoopFactory = previous
	}
}

type fakeBootstrapProvider struct{}

func (fakeBootstrapProvider) Bucket() string { return "assets" }

func (fakeBootstrapProvider) SignPutObject(context.Context, string, time.Duration, string) (string, error) {
	return "", errors.New("not implemented")
}

func (fakeBootstrapProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", errors.New("not implemented")
}

func (fakeBootstrapProvider) StatObject(context.Context, string) (*storage.ObjectStat, error) {
	return nil, errors.New("not implemented")
}

func (fakeBootstrapProvider) DownloadObject(context.Context, string, string) error {
	return errors.New("not implemented")
}
