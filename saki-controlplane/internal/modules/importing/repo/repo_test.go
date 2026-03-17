package repo

import (
	"context"
	"database/sql"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestImportSchemaUsesDatasetScopedPreviewAndMatchRefs(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startImportPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, importMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	assertHasColumn(t, sqlDB, "import_preview_manifest", "dataset_id")
	assertHasColumn(t, sqlDB, "sample_match_ref", "dataset_id")
	assertMissingColumn(t, sqlDB, "sample_match_ref", "project_id")
}

func TestImportReposSessionPreviewTaskAndMatchRef(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startImportPostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, importMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	uploadRepo := NewUploadRepo(pool)
	userID := uuid.New()
	session, err := uploadRepo.Init(ctx, InitUploadSessionParams{
		UserID:      userID,
		Mode:        "project_annotations",
		FileName:    "annotations.zip",
		ObjectKey:   "imports/user/annotations.zip",
		ContentType: "application/zip",
	})
	if err != nil {
		t.Fatalf("init upload session: %v", err)
	}
	if got, want := session.Status, "initiated"; got != want {
		t.Fatalf("upload session status got %q want %q", got, want)
	}

	loadedSession, err := uploadRepo.Get(ctx, session.ID)
	if err != nil {
		t.Fatalf("get upload session: %v", err)
	}
	if loadedSession == nil || loadedSession.ID != session.ID {
		t.Fatalf("unexpected upload session lookup: %+v", loadedSession)
	}

	completedSession, err := uploadRepo.MarkCompleted(ctx, session.ID)
	if err != nil {
		t.Fatalf("mark upload completed: %v", err)
	}
	if got, want := completedSession.Status, "completed"; got != want {
		t.Fatalf("completed upload session status got %q want %q", got, want)
	}
	if completedSession.CompletedAt == nil {
		t.Fatal("expected completed_at to be set")
	}

	previewRepo := NewPreviewRepo(pool)
	expiresAt := time.Now().Add(15 * time.Minute).UTC().Truncate(time.Microsecond)
	datasetID := uuid.New()
	if _, err := sqlDB.ExecContext(ctx, `insert into dataset (id, name, type) values ($1, $2, $3)`, datasetID, "demo-dataset", "image"); err != nil {
		t.Fatalf("seed dataset: %v", err)
	}
	manifest, err := previewRepo.Put(ctx, PutPreviewManifestParams{
		Token:           "preview-token-1",
		Mode:            "project_annotations",
		ProjectID:       uuid.New(),
		DatasetID:       datasetID,
		UploadSessionID: session.ID,
		Manifest:        []byte(`{"summary":{"total_annotations":1}}`),
		ParamsHash:      "hash-1",
		ExpiresAt:       expiresAt,
	})
	if err != nil {
		t.Fatalf("put preview manifest: %v", err)
	}
	if got, want := manifest.Token, "preview-token-1"; got != want {
		t.Fatalf("preview token got %q want %q", got, want)
	}

	loadedManifest, err := previewRepo.Get(ctx, "preview-token-1")
	if err != nil {
		t.Fatalf("get preview manifest: %v", err)
	}
	if loadedManifest == nil {
		t.Fatalf("unexpected preview manifest: %+v", loadedManifest)
	}
	if !jsonEqual(t, loadedManifest.Manifest, []byte(`{"summary":{"total_annotations":1}}`)) {
		t.Fatalf("unexpected preview manifest: %+v", loadedManifest)
	}

	taskRepo := NewTaskRepo(pool)
	taskID := uuid.New()
	task, err := taskRepo.Create(ctx, CreateTaskParams{
		ID:           taskID,
		UserID:       userID,
		Mode:         "project_annotations_execute",
		ResourceType: "project",
		ResourceID:   uuid.New(),
		Payload:      []byte(`{"preview_token":"preview-token-1"}`),
	})
	if err != nil {
		t.Fatalf("create import task: %v", err)
	}
	if got, want := task.Status, "queued"; got != want {
		t.Fatalf("task status got %q want %q", got, want)
	}

	firstEvent, err := taskRepo.AppendEvent(ctx, AppendTaskEventParams{
		TaskID:  taskID,
		Event:   "start",
		Phase:   "prepare",
		Payload: []byte(`{"message":"started"}`),
	})
	if err != nil {
		t.Fatalf("append first task event: %v", err)
	}
	secondEvent, err := taskRepo.AppendEvent(ctx, AppendTaskEventParams{
		TaskID:  taskID,
		Event:   "complete",
		Phase:   "prepare",
		Payload: []byte(`{"message":"done"}`),
	})
	if err != nil {
		t.Fatalf("append second task event: %v", err)
	}
	if !(secondEvent.Seq > firstEvent.Seq) {
		t.Fatalf("expected increasing seq, got first=%d second=%d", firstEvent.Seq, secondEvent.Seq)
	}

	events, err := taskRepo.ListEventsAfter(ctx, taskID, 0, 10)
	if err != nil {
		t.Fatalf("list task events: %v", err)
	}
	if got, want := len(events), 2; got != want {
		t.Fatalf("task events len got %d want %d", got, want)
	}
	if got := []string{events[0].Event, events[1].Event}; !slices.Equal(got, []string{"start", "complete"}) {
		t.Fatalf("unexpected task events: %+v", got)
	}

	sampleRepo := annotationrepo.NewSampleRepo(pool)
	sample, err := sampleRepo.Create(ctx, annotationrepo.CreateSampleParams{
		DatasetID: datasetID,
		Name:      "sample-1",
		Meta:      []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create sample: %v", err)
	}

	matchRepo := NewSampleMatchRefRepo(pool)
	ref, err := matchRepo.Put(ctx, PutSampleMatchRefParams{
		DatasetID: datasetID,
		SampleID:  sample.ID,
		RefType:   "dataset_relpath",
		RefValue:  "images/train/sample1.png",
		IsPrimary: true,
	})
	if err != nil {
		t.Fatalf("put sample match ref: %v", err)
	}
	if got, want := ref.RefValue, "images/train/sample1.png"; got != want {
		t.Fatalf("sample match ref value got %q want %q", got, want)
	}

	matches, err := matchRepo.FindExact(ctx, datasetID, "dataset_relpath", "images/train/sample1.png")
	if err != nil {
		t.Fatalf("find exact match refs: %v", err)
	}
	if got, want := len(matches), 1; got != want {
		t.Fatalf("matches len got %d want %d", got, want)
	}
	if got, want := matches[0].SampleID, sample.ID; got != want {
		t.Fatalf("match sample_id got %s want %s", got, want)
	}
}

func startImportPostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		importPostgresImageRef(),
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

func importMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func importPostgresImageRef() string {
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
