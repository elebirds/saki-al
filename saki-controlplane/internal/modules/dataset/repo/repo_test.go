package repo

import (
	"context"
	"database/sql"
	"os/exec"
	"path/filepath"
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

func TestDatasetRepoCreateGetListUpdateDelete(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startDatasetPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, datasetMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewDatasetRepo(pool)
	created, err := repo.Create(ctx, CreateDatasetParams{
		Name: "dataset-a",
		Type: "image",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}
	if created == nil || created.ID == uuid.Nil {
		t.Fatalf("unexpected created dataset: %+v", created)
	}

	loaded, err := repo.Get(ctx, created.ID)
	if err != nil {
		t.Fatalf("get dataset: %v", err)
	}
	if loaded == nil || loaded.Name != "dataset-a" || loaded.Type != "image" {
		t.Fatalf("unexpected loaded dataset: %+v", loaded)
	}

	listed, err := repo.List(ctx, ListDatasetsParams{
		Query:  "",
		Offset: 0,
		Limit:  20,
	})
	if err != nil {
		t.Fatalf("list datasets: %v", err)
	}
	if listed.Total != 1 || listed.Offset != 0 || listed.Limit != 20 {
		t.Fatalf("unexpected dataset page: %+v", listed)
	}
	if len(listed.Items) != 1 || listed.Items[0].ID != created.ID {
		t.Fatalf("unexpected listed datasets: %+v", listed.Items)
	}

	time.Sleep(5 * time.Millisecond)

	updated, err := repo.Update(ctx, UpdateDatasetParams{
		ID:   created.ID,
		Name: "dataset-b",
		Type: "lidar",
	})
	if err != nil {
		t.Fatalf("update dataset: %v", err)
	}
	if updated.Name != "dataset-b" || updated.Type != "lidar" {
		t.Fatalf("unexpected updated dataset: %+v", updated)
	}
	if !updated.UpdatedAt.After(created.UpdatedAt) {
		t.Fatalf("expected updated_at to change after update, created=%s updated=%s", created.UpdatedAt, updated.UpdatedAt)
	}

	deletedOK, err := repo.Delete(ctx, created.ID)
	if err != nil {
		t.Fatalf("delete dataset: %v", err)
	}
	if !deletedOK {
		t.Fatal("expected delete to report success")
	}

	deleted, err := repo.Get(ctx, created.ID)
	if err != nil {
		t.Fatalf("get deleted dataset: %v", err)
	}
	if deleted != nil {
		t.Fatalf("expected deleted dataset to be absent, got %+v", deleted)
	}
}

func TestDatasetRepoListSupportsPaginationAndQuery(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startDatasetPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, datasetMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewDatasetRepo(pool)
	for _, params := range []CreateDatasetParams{
		{Name: "alpha", Type: "image"},
		{Name: "beta", Type: "image"},
		{Name: "alpine", Type: "image"},
	} {
		if _, err := repo.Create(ctx, params); err != nil {
			t.Fatalf("create dataset: %v", err)
		}
	}

	page, err := repo.List(ctx, ListDatasetsParams{
		Query:  "alp",
		Offset: 1,
		Limit:  1,
	})
	if err != nil {
		t.Fatalf("list datasets with filter: %v", err)
	}
	if page.Total != 2 || page.Offset != 1 || page.Limit != 1 {
		t.Fatalf("unexpected dataset page: %+v", page)
	}
	if len(page.Items) != 1 || page.Items[0].Name != "alpine" {
		t.Fatalf("unexpected filtered datasets: %+v", page.Items)
	}
}

func TestDatasetRepoDeleteReportsWhetherRowWasRemoved(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startDatasetPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, datasetMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	repo := NewDatasetRepo(pool)
	created, err := repo.Create(ctx, CreateDatasetParams{
		Name: "dataset-a",
		Type: "image",
	})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}

	deleted, err := repo.Delete(ctx, created.ID)
	if err != nil {
		t.Fatalf("delete existing dataset: %v", err)
	}
	if !deleted {
		t.Fatal("expected delete to report an affected row")
	}

	deleted, err = repo.Delete(ctx, created.ID)
	if err != nil {
		t.Fatalf("delete missing dataset: %v", err)
	}
	if deleted {
		t.Fatal("expected delete to report zero affected rows")
	}
}

func startDatasetPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		datasetPostgresImageRef(),
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

func datasetMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func datasetPostgresImageRef() string {
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
