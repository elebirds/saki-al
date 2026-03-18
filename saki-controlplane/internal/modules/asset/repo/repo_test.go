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
	if created.ReadyAt != nil {
		t.Fatalf("pending asset ready_at got %v want nil", created.ReadyAt)
	}
	if created.OrphanedAt != nil {
		t.Fatalf("pending asset orphaned_at got %v want nil", created.OrphanedAt)
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
	if updated.ReadyAt == nil {
		t.Fatal("expected ready asset ready_at to be populated")
	}
	if updated.OrphanedAt != nil {
		t.Fatalf("ready asset orphaned_at got %v want nil", updated.OrphanedAt)
	}
	if !updated.UpdatedAt.After(created.UpdatedAt) {
		t.Fatalf("expected updated_at to move forward, created=%s updated=%s", created.UpdatedAt, updated.UpdatedAt)
	}

	repeated, err := repo.MarkReady(ctx, MarkReadyParams{
		ID:          created.ID,
		SizeBytes:   9999,
		Sha256Hex:   stringPtr("should-not-apply"),
		ContentType: "image/jpeg",
	})
	if err != nil {
		t.Fatalf("repeat mark asset ready: %v", err)
	}
	if repeated != nil {
		t.Fatalf("expected repeat mark ready to return nil, got %+v", repeated)
	}

	reloaded, err := repo.Get(ctx, created.ID)
	if err != nil {
		t.Fatalf("reload asset after repeated mark ready: %v", err)
	}
	if reloaded == nil {
		t.Fatal("expected asset to still exist")
	}
	if got, want := reloaded.SizeBytes, int64(1234); got != want {
		t.Fatalf("reloaded asset size got %d want %d", got, want)
	}
	if reloaded.Sha256Hex == nil || *reloaded.Sha256Hex != "abc123" {
		t.Fatalf("reloaded asset sha got %+v want abc123", reloaded.Sha256Hex)
	}
	if got, want := reloaded.ContentType, "image/webp"; got != want {
		t.Fatalf("reloaded asset content_type got %q want %q", got, want)
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

func TestAssetRepoCreatePendingNormalizesNilMetadata(t *testing.T) {
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
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "raw/nil-metadata.png",
		ContentType:    "image/png",
		Metadata:       nil,
	})
	if err != nil {
		t.Fatalf("create pending asset with nil metadata: %v", err)
	}
	if !jsonEqual(t, created.Metadata, []byte(`{}`)) {
		t.Fatalf("asset metadata got %s want {}", created.Metadata)
	}
}

func TestAssetSchemaIncludesReadyAtAndOrphanedAt(t *testing.T) {
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

	var count int
	if err := sqlDB.QueryRow(`
		select count(*)
		from information_schema.columns
		where table_schema = 'public'
		  and table_name = 'asset'
		  and column_name in ('ready_at', 'orphaned_at')
	`).Scan(&count); err != nil {
		t.Fatalf("count asset columns: %v", err)
	}

	if got, want := count, 2; got != want {
		t.Fatalf("asset ready_at/orphaned_at column count got %d want %d", got, want)
	}
}

func TestAssetSchemaUsesStorageScopedUniqueKey(t *testing.T) {
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

	rows, err := sqlDB.Query(`
		select pg_get_constraintdef(c.oid)
		from pg_constraint c
		join pg_class t on t.oid = c.conrelid
		join pg_namespace n on n.oid = t.relnamespace
		where n.nspname = 'public'
		  and t.relname = 'asset'
		  and c.contype = 'u'
	`)
	if err != nil {
		t.Fatalf("query asset unique constraints: %v", err)
	}
	defer rows.Close()

	var defs []string
	for rows.Next() {
		var def string
		if err := rows.Scan(&def); err != nil {
			t.Fatalf("scan unique constraint: %v", err)
		}
		defs = append(defs, strings.ToLower(def))
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("iterate unique constraints: %v", err)
	}
	if len(defs) == 0 {
		t.Fatal("expected at least one unique constraint on asset")
	}

	hasStorageScopedKey := false
	hasLegacyBucketObjectKey := false
	for _, def := range defs {
		if strings.Contains(def, "unique (storage_backend, bucket, object_key)") {
			hasStorageScopedKey = true
		}
		if strings.Contains(def, "unique (bucket, object_key)") {
			hasLegacyBucketObjectKey = true
		}
	}

	if !hasStorageScopedKey {
		t.Fatalf("missing unique(storage_backend, bucket, object_key), got constraints: %v", defs)
	}
	if hasLegacyBucketObjectKey {
		t.Fatalf("unexpected legacy unique(bucket, object_key), got constraints: %v", defs)
	}
}

func TestAssetDurableUploadTablesExist(t *testing.T) {
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

	var assetReferenceRegclass string
	if err := sqlDB.QueryRow(`select coalesce(to_regclass('public.asset_reference')::text, '')`).Scan(&assetReferenceRegclass); err != nil {
		t.Fatalf("check asset_reference table: %v", err)
	}
	if got, want := assetReferenceRegclass, "asset_reference"; got != want {
		t.Fatalf("asset_reference table got %q want %q", got, want)
	}

	var assetUploadIntentRegclass string
	if err := sqlDB.QueryRow(`select coalesce(to_regclass('public.asset_upload_intent')::text, '')`).Scan(&assetUploadIntentRegclass); err != nil {
		t.Fatalf("check asset_upload_intent table: %v", err)
	}
	if got, want := assetUploadIntentRegclass, "asset_upload_intent"; got != want {
		t.Fatalf("asset_upload_intent table got %q want %q", got, want)
	}

	var declaredContentTypeCount int
	if err := sqlDB.QueryRow(`
		select count(*)
		from information_schema.columns
		where table_schema = 'public'
		  and table_name = 'asset_upload_intent'
		  and column_name = 'declared_content_type'
	`).Scan(&declaredContentTypeCount); err != nil {
		t.Fatalf("check declared_content_type column: %v", err)
	}
	if got, want := declaredContentTypeCount, 1; got != want {
		t.Fatalf("asset_upload_intent.declared_content_type count got %d want %d", got, want)
	}
}

func TestAssetUploadIntentUsesCascadeDelete(t *testing.T) {
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

	rows, err := sqlDB.Query(`
		select pg_get_constraintdef(c.oid)
		from pg_constraint c
		join pg_class t on t.oid = c.conrelid
		join pg_namespace n on n.oid = t.relnamespace
		where n.nspname = 'public'
		  and t.relname = 'asset_upload_intent'
		  and c.contype = 'f'
	`)
	if err != nil {
		t.Fatalf("query asset_upload_intent foreign keys: %v", err)
	}
	defer rows.Close()

	var defs []string
	for rows.Next() {
		var def string
		if err := rows.Scan(&def); err != nil {
			t.Fatalf("scan foreign key constraint: %v", err)
		}
		defs = append(defs, strings.ToLower(def))
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("iterate foreign key constraints: %v", err)
	}

	hasCascadeFK := false
	for _, def := range defs {
		if strings.Contains(def, "foreign key (asset_id)") &&
			strings.Contains(def, "references asset(id)") &&
			strings.Contains(def, "on delete cascade") {
			hasCascadeFK = true
			break
		}
	}

	if !hasCascadeFK {
		t.Fatalf("missing asset_upload_intent.asset_id -> asset(id) on delete cascade, got constraints: %v", defs)
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
