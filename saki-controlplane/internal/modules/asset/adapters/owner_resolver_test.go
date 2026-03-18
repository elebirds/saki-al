package adapters

import (
	"context"
	"database/sql"
	"errors"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	datasetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestOwnerResolverResolvesProjectDatasetAndSample(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startOwnerResolverPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, ownerResolverMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	projectRepo := projectrepo.NewProjectRepo(pool)
	datasetRepo := datasetrepo.NewDatasetRepo(pool)
	sampleRepo := annotationrepo.NewSampleRepo(pool)
	resolver := NewOwnerResolver(pool)

	project, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "project-a"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}
	dataset, err := datasetRepo.Create(ctx, datasetrepo.CreateDatasetParams{Name: "dataset-a", Type: "image"})
	if err != nil {
		t.Fatalf("create dataset: %v", err)
	}
	sample, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: dataset.ID,
		Name:      "sample-a",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	resolvedProject, err := resolver.Resolve(ctx, assetapp.AssetOwnerTypeProject, project.ID)
	if err != nil {
		t.Fatalf("resolve project owner: %v", err)
	}
	if resolvedProject == nil || resolvedProject.OwnerID != project.ID || resolvedProject.OwnerType != assetapp.AssetOwnerTypeProject {
		t.Fatalf("unexpected resolved project owner: %+v", resolvedProject)
	}
	if resolvedProject.DatasetID != nil {
		t.Fatalf("expected project owner dataset_id nil, got %v", resolvedProject.DatasetID)
	}

	resolvedDataset, err := resolver.Resolve(ctx, assetapp.AssetOwnerTypeDataset, dataset.ID)
	if err != nil {
		t.Fatalf("resolve dataset owner: %v", err)
	}
	if resolvedDataset == nil || resolvedDataset.OwnerID != dataset.ID || resolvedDataset.OwnerType != assetapp.AssetOwnerTypeDataset {
		t.Fatalf("unexpected resolved dataset owner: %+v", resolvedDataset)
	}
	if resolvedDataset.DatasetID != nil {
		t.Fatalf("expected dataset owner dataset_id nil, got %v", resolvedDataset.DatasetID)
	}

	resolvedSample, err := resolver.Resolve(ctx, assetapp.AssetOwnerTypeSample, sample.ID)
	if err != nil {
		t.Fatalf("resolve sample owner: %v", err)
	}
	if resolvedSample == nil || resolvedSample.OwnerID != sample.ID || resolvedSample.OwnerType != assetapp.AssetOwnerTypeSample {
		t.Fatalf("unexpected resolved sample owner: %+v", resolvedSample)
	}
	if resolvedSample.DatasetID == nil || *resolvedSample.DatasetID != dataset.ID {
		t.Fatalf("expected sample owner dataset_id %s, got %+v", dataset.ID, resolvedSample.DatasetID)
	}
}

func TestOwnerResolverRejectsUnsupportedOwnerType(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startOwnerResolverPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, ownerResolverMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	resolver := NewOwnerResolver(pool)

	owner, err := resolver.Resolve(ctx, assetapp.AssetOwnerType("runtime"), uuid.New())
	if !errors.Is(err, assetapp.ErrUnsupportedAssetOwnerType) {
		t.Fatalf("expected ErrUnsupportedAssetOwnerType, got owner=%+v err=%v", owner, err)
	}
}

func TestOwnerResolverReturnsNilWhenOwnerMissing(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startOwnerResolverPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, ownerResolverMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	resolver := NewOwnerResolver(pool)

	owner, err := resolver.Resolve(ctx, assetapp.AssetOwnerTypeDataset, uuid.New())
	if err != nil {
		t.Fatalf("resolve missing dataset owner: %v", err)
	}
	if owner != nil {
		t.Fatalf("expected missing owner to return nil, got %+v", owner)
	}
}

func TestOwnerResolverCanBindToTransactionSnapshot(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startOwnerResolverPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, ownerResolverMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	projectRepo := projectrepo.NewProjectRepo(pool)
	project, err := projectRepo.CreateProject(ctx, projectrepo.CreateProjectParams{Name: "project-tx"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}

	tx, err := pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	defer tx.Rollback(ctx)

	resolver := NewOwnerResolver(tx)
	resolved, err := resolver.Resolve(ctx, assetapp.AssetOwnerTypeProject, project.ID)
	if err != nil {
		t.Fatalf("resolve project owner in tx: %v", err)
	}
	if resolved == nil || resolved.OwnerID != project.ID {
		t.Fatalf("unexpected resolved owner in tx: %+v", resolved)
	}
}

func startOwnerResolverPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		ownerResolverPostgresImageRef(),
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

func ownerResolverMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func ownerResolverPostgresImageRef() string {
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
