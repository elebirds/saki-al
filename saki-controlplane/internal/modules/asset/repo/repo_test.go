package repo

import (
	"context"
	"database/sql"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestAssetRepoCreatePendingAndMarkReady(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAssetPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, assetMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	userID := uuid.New()
	repo := NewAssetRepo(pool)
	created, err := repo.CreatePending(ctx, CreatePendingParams{
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "raw/demo.png",
		ContentType:    "image/png",
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedBy:      &userID,
	})
	if err != nil {
		t.Fatalf("create pending asset: %v", err)
	}
	if created == nil || created.ID == uuid.Nil {
		t.Fatalf("unexpected created asset: %+v", created)
	}
	if got, want := created.Status, AssetStatusPendingUpload; got != want {
		t.Fatalf("asset status got %q want %q", got, want)
	}
	if got, want := created.SizeBytes, int64(0); got != want {
		t.Fatalf("asset size got %d want %d", got, want)
	}
	if !jsonEqual(t, created.Metadata, []byte(`{"source":"camera"}`)) {
		t.Fatalf("asset metadata got %s want %s", created.Metadata, `{"source":"camera"}`)
	}
	if created.CreatedBy == nil || *created.CreatedBy != userID {
		t.Fatalf("asset created_by got %+v want %s", created.CreatedBy, userID)
	}

	loaded, err := repo.Get(ctx, created.ID)
	if err != nil {
		t.Fatalf("get asset: %v", err)
	}
	if loaded == nil || loaded.ID != created.ID {
		t.Fatalf("unexpected loaded asset: %+v", loaded)
	}

	time.Sleep(5 * time.Millisecond)

	updated, err := repo.MarkReady(ctx, MarkReadyParams{
		ID:          created.ID,
		SizeBytes:   1234,
		Sha256Hex:   stringPtr("abc123"),
		ContentType: "image/webp",
	})
	if err != nil {
		t.Fatalf("mark asset ready: %v", err)
	}
	if got, want := updated.Status, AssetStatusReady; got != want {
		t.Fatalf("updated asset status got %q want %q", got, want)
	}
	if got, want := updated.SizeBytes, int64(1234); got != want {
		t.Fatalf("updated asset size got %d want %d", got, want)
	}
	if updated.Sha256Hex == nil || *updated.Sha256Hex != "abc123" {
		t.Fatalf("updated asset sha got %+v want abc123", updated.Sha256Hex)
	}
	if got, want := updated.ContentType, "image/webp"; got != want {
		t.Fatalf("updated asset content_type got %q want %q", got, want)
	}
	if !updated.UpdatedAt.After(created.UpdatedAt) {
		t.Fatalf("expected updated_at to move forward, created=%s updated=%s", created.UpdatedAt, updated.UpdatedAt)
	}
}

func TestAssetRepoGetByStorageLocation(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAssetPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, assetMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewAssetRepo(pool)
	created, err := repo.CreatePending(ctx, CreatePendingParams{
		Kind:           "archive",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "uploads/demo.zip",
		ContentType:    "application/zip",
		Metadata:       []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create pending asset: %v", err)
	}

	loaded, err := repo.GetByStorageLocation(ctx, "assets", "uploads/demo.zip")
	if err != nil {
		t.Fatalf("get asset by storage location: %v", err)
	}
	if loaded == nil || loaded.ID != created.ID {
		t.Fatalf("unexpected asset lookup result: %+v", loaded)
	}

	missing, err := repo.GetByStorageLocation(ctx, "assets", "missing.zip")
	if err != nil {
		t.Fatalf("get missing asset by storage location: %v", err)
	}
	if missing != nil {
		t.Fatalf("expected missing asset lookup to return nil, got %+v", missing)
	}
}

func startAssetPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		assetPostgresImageRef(),
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

func assetMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func assetPostgresImageRef() string {
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

func stringPtr(v string) *string {
	return &v
}

func jsonEqual(t *testing.T, left, right []byte) bool {
	t.Helper()

	var leftValue any
	if err := json.Unmarshal(left, &leftValue); err != nil {
		t.Fatalf("unmarshal left json: %v", err)
	}
	var rightValue any
	if err := json.Unmarshal(right, &rightValue); err != nil {
		t.Fatalf("unmarshal right json: %v", err)
	}
	return reflect.DeepEqual(leftValue, rightValue)
}
