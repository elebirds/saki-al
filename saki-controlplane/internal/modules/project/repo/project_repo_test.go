package repo

import (
	"context"
	"database/sql"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestProjectSchemaIncludesProjectDatasetLinkTable(t *testing.T) {
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

	assertHasColumn(t, sqlDB, "project_dataset", "project_id")
	assertHasColumn(t, sqlDB, "project_dataset", "dataset_id")
}

func TestProjectRepoCreateProject(t *testing.T) {
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

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	projectRepo := NewProjectRepo(pool)
	project, err := projectRepo.CreateProject(ctx, CreateProjectParams{
		Name: "foundation-project",
	})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}

	if project.ID == uuid.Nil {
		t.Fatal("expected generated project id")
	}
	if project.Name != "foundation-project" {
		t.Fatalf("unexpected project name: %s", project.Name)
	}
	if project.CreatedAt.IsZero() {
		t.Fatal("expected created_at to be populated")
	}
	if project.UpdatedAt.IsZero() {
		t.Fatal("expected updated_at to be populated")
	}
}

func TestProjectRepoCanLinkAndListDatasets(t *testing.T) {
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

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	projectRepo := NewProjectRepo(pool)
	project, err := projectRepo.CreateProject(ctx, CreateProjectParams{Name: "linked-project"})
	if err != nil {
		t.Fatalf("create project: %v", err)
	}

	datasetID := uuid.New()
	if _, err := sqlDB.ExecContext(ctx, `insert into dataset (id, name, type) values ($1, $2, $3)`, datasetID, "dataset-1", "image"); err != nil {
		t.Fatalf("seed dataset: %v", err)
	}

	link, err := projectRepo.LinkDataset(ctx, project.ID, datasetID)
	if err != nil {
		t.Fatalf("link dataset: %v", err)
	}
	if link.ProjectID != project.ID || link.DatasetID != datasetID {
		t.Fatalf("unexpected project dataset link: %+v", link)
	}

	linkedIDs, err := projectRepo.ListProjectDatasetIDs(ctx, project.ID)
	if err != nil {
		t.Fatalf("list linked dataset ids: %v", err)
	}
	if len(linkedIDs) != 1 || linkedIDs[0] != datasetID {
		t.Fatalf("unexpected linked dataset ids: %+v", linkedIDs)
	}

	loadedLink, err := projectRepo.GetProjectDatasetLink(ctx, project.ID, datasetID)
	if err != nil {
		t.Fatalf("get project dataset link: %v", err)
	}
	if loadedLink == nil || loadedLink.ProjectID != project.ID || loadedLink.DatasetID != datasetID {
		t.Fatalf("unexpected loaded project dataset link: %+v", loadedLink)
	}
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
			wait.ForLog("database system is ready to accept connections").
				WithOccurrence(2),
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

func assertHasColumn(t *testing.T, db *sql.DB, tableName, columnName string) {
	t.Helper()

	var exists bool
	row := db.QueryRow(`
select exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = $1
      and column_name = $2
)`, tableName, columnName)
	if err := row.Scan(&exists); err != nil {
		t.Fatalf("scan column existence for %s.%s: %v", tableName, columnName, err)
	}
	if !exists {
		t.Fatalf("expected column %s.%s to exist", tableName, columnName)
	}
}
