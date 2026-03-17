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

func TestAnnotationSchemaUsesDatasetBackedSamples(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAnnotationPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, annotationMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	assertHasColumn(t, sqlDB, "dataset", "id")
	assertHasColumn(t, sqlDB, "project_dataset", "project_id")
	assertHasColumn(t, sqlDB, "project_dataset", "dataset_id")
	assertHasColumn(t, sqlDB, "sample", "dataset_id")
	assertMissingColumn(t, sqlDB, "sample", "project_id")
	assertHasColumn(t, sqlDB, "annotation", "project_id")
}

func TestSampleAndAnnotationReposCreateAndList(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startAnnotationPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, annotationMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	sampleRepo := NewSampleRepo(pool)
	projectID := uuid.New()
	datasetID := uuid.New()
	if _, err := sqlDB.ExecContext(ctx, `insert into dataset (id, name, type) values ($1, $2, $3)`, datasetID, "demo-dataset", "image"); err != nil {
		t.Fatalf("seed dataset: %v", err)
	}
	if _, err := sqlDB.ExecContext(ctx, `insert into project (id, name) values ($1, $2)`, projectID, "demo-project"); err != nil {
		t.Fatalf("seed project: %v", err)
	}
	if _, err := sqlDB.ExecContext(ctx, `insert into project_dataset (project_id, dataset_id) values ($1, $2)`, projectID, datasetID); err != nil {
		t.Fatalf("seed project dataset link: %v", err)
	}

	sample, err := sampleRepo.Create(ctx, CreateSampleParams{
		DatasetID: datasetID,
		Name:      "sample-1",
		Meta:      []byte(`{"source_view":"rgb","target_view":"thermal","lookup_ref":"lut-1"}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}
	if sample.ID == uuid.Nil || sample.DatasetID != datasetID {
		t.Fatalf("unexpected sample: %+v", sample)
	}

	loadedSample, err := sampleRepo.Get(ctx, sample.ID)
	if err != nil {
		t.Fatalf("get sample: %v", err)
	}
	if loadedSample == nil || loadedSample.DatasetID != datasetID || loadedSample.Name != "sample-1" || string(loadedSample.Meta) == "" {
		t.Fatalf("unexpected loaded sample: %+v", loadedSample)
	}

	annotationRepo := NewAnnotationRepo(pool)
	created, err := annotationRepo.Create(ctx, CreateAnnotationParams{
		ProjectID:      projectID,
		SampleID:       sample.ID,
		GroupID:        "group-a",
		LabelID:        "car",
		View:           "rgb",
		AnnotationType: "obb",
		Geometry:       []byte(`{"cx":10,"cy":20,"w":5,"h":6,"angle":30}`),
		Attrs:          []byte(`{"score":0.9}`),
		Source:         "manual",
		IsGenerated:    false,
	})
	if err != nil {
		t.Fatalf("create annotation: %v", err)
	}
	if created.ID == uuid.Nil || created.ProjectID != projectID || created.SampleID != sample.ID {
		t.Fatalf("unexpected created annotation: %+v", created)
	}

	listed, err := annotationRepo.ListByProjectSample(ctx, projectID, sample.ID)
	if err != nil {
		t.Fatalf("list annotations: %v", err)
	}
	if len(listed) != 1 {
		t.Fatalf("unexpected annotation count: %d", len(listed))
	}
	if listed[0].View != "rgb" || listed[0].AnnotationType != "obb" || listed[0].Source != "manual" {
		t.Fatalf("unexpected listed annotation: %+v", listed[0])
	}
	if string(listed[0].Geometry) == "" || string(listed[0].Attrs) == "" {
		t.Fatalf("expected geometry and attrs to persist: %+v", listed[0])
	}
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

func assertMissingColumn(t *testing.T, db *sql.DB, tableName, columnName string) {
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
	if exists {
		t.Fatalf("expected column %s.%s to be absent", tableName, columnName)
	}
}
