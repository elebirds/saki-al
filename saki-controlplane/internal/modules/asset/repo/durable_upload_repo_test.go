package repo

import (
	"context"
	"database/sql"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
)

func TestUploadIntentRepoCreateGetAndMarkExpired(t *testing.T) {
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

	assetRepo := NewAssetRepo(pool)
	intentRepo := NewAssetUploadIntentRepo(pool)

	userID := uuid.New()
	ownerID := uuid.New()
	asset, err := assetRepo.CreatePending(ctx, CreatePendingParams{
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "raw/intent.png",
		ContentType:    "image/png",
		Metadata:       []byte(`{"source":"camera"}`),
		CreatedBy:      &userID,
	})
	if err != nil {
		t.Fatalf("create pending asset: %v", err)
	}

	expiresAt := time.Now().Add(15 * time.Minute).UTC().Truncate(time.Microsecond)
	created, err := intentRepo.Create(ctx, CreateAssetUploadIntentParams{
		AssetID:             asset.ID,
		OwnerType:           "dataset",
		OwnerID:             ownerID,
		Role:                "attachment",
		IsPrimary:           false,
		DeclaredContentType: "image/png",
		IdempotencyKey:      "idem-1",
		ExpiresAt:           expiresAt,
		CreatedBy:           &userID,
	})
	if err != nil {
		t.Fatalf("create upload intent: %v", err)
	}
	if created == nil || created.AssetID != asset.ID {
		t.Fatalf("unexpected created intent: %+v", created)
	}
	if got, want := created.State, "initiated"; got != want {
		t.Fatalf("intent state got %q want %q", got, want)
	}

	loadedByAssetID, err := intentRepo.GetByAssetID(ctx, asset.ID)
	if err != nil {
		t.Fatalf("get intent by asset id: %v", err)
	}
	if loadedByAssetID == nil || loadedByAssetID.ID != created.ID {
		t.Fatalf("unexpected intent by asset id: %+v", loadedByAssetID)
	}

	loadedByOwnerKey, err := intentRepo.GetByOwnerKey(ctx, GetAssetUploadIntentByOwnerKeyParams{
		OwnerType:      "dataset",
		OwnerID:        ownerID,
		Role:           "attachment",
		IdempotencyKey: "idem-1",
	})
	if err != nil {
		t.Fatalf("get intent by owner key: %v", err)
	}
	if loadedByOwnerKey == nil || loadedByOwnerKey.ID != created.ID {
		t.Fatalf("unexpected intent by owner key: %+v", loadedByOwnerKey)
	}

	expiredAt := time.Now().Add(30 * time.Minute).UTC().Truncate(time.Microsecond)
	expired, err := intentRepo.MarkExpired(ctx, MarkAssetUploadIntentExpiredParams{
		AssetID:   asset.ID,
		ExpiredAt: expiredAt,
	})
	if err != nil {
		t.Fatalf("mark intent expired: %v", err)
	}
	if expired == nil {
		t.Fatal("expected expired intent")
	}
	if got, want := expired.State, "expired"; got != want {
		t.Fatalf("expired intent state got %q want %q", got, want)
	}
}

func TestDurableUploadRepoCreateReferenceAndMaintainOrphanedAt(t *testing.T) {
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

	assetRepo := NewAssetRepo(pool)
	referenceRepo := NewAssetReferenceRepo(pool)

	userID := uuid.New()
	asset, err := assetRepo.CreatePending(ctx, CreatePendingParams{
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "raw/reference.png",
		ContentType:    "image/png",
		Metadata:       []byte(`{}`),
		CreatedBy:      &userID,
	})
	if err != nil {
		t.Fatalf("create pending asset: %v", err)
	}

	readyAsset, err := assetRepo.MarkReady(ctx, MarkReadyParams{
		ID:          asset.ID,
		SizeBytes:   128,
		Sha256Hex:   stringPtr("abc123"),
		ContentType: "image/png",
	})
	if err != nil {
		t.Fatalf("mark asset ready: %v", err)
	}
	if readyAsset == nil {
		t.Fatal("expected ready asset")
	}
	if readyAsset.OrphanedAt != nil {
		t.Fatalf("expected ready asset orphaned_at nil, got %v", readyAsset.OrphanedAt)
	}

	ownerID := uuid.New()
	createdRef, err := referenceRepo.CreateDurable(ctx, CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "project",
		OwnerID:   ownerID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
		Metadata:  nil,
		CreatedBy: &userID,
	})
	if err != nil {
		t.Fatalf("create durable reference: %v", err)
	}
	if createdRef == nil || createdRef.AssetID != asset.ID {
		t.Fatalf("unexpected durable reference: %+v", createdRef)
	}

	count, err := referenceRepo.CountActiveForAsset(ctx, asset.ID)
	if err != nil {
		t.Fatalf("count active references: %v", err)
	}
	if got, want := count, int64(1); got != want {
		t.Fatalf("active reference count got %d want %d", got, want)
	}

	deletedAt := time.Now().UTC().Truncate(time.Microsecond)
	invalidated, err := referenceRepo.InvalidateForOwner(ctx, InvalidateAssetReferencesForOwnerParams{
		OwnerType: "project",
		OwnerID:   ownerID,
		DeletedAt: deletedAt,
	})
	if err != nil {
		t.Fatalf("invalidate durable references: %v", err)
	}
	if got, want := invalidated, int64(1); got != want {
		t.Fatalf("invalidated references got %d want %d", got, want)
	}

	orphanedAsset, err := assetRepo.Get(ctx, asset.ID)
	if err != nil {
		t.Fatalf("get orphaned asset: %v", err)
	}
	if orphanedAsset == nil || orphanedAsset.OrphanedAt == nil {
		t.Fatalf("expected orphaned_at to be populated, got %+v", orphanedAsset)
	}

	secondOwnerID := uuid.New()
	if _, err := referenceRepo.CreateDurable(ctx, CreateAssetReferenceParams{
		AssetID:   asset.ID,
		OwnerType: "dataset",
		OwnerID:   secondOwnerID,
		Role:      "attachment",
		Lifecycle: "durable",
		IsPrimary: false,
		Metadata:  nil,
		CreatedBy: &userID,
	}); err != nil {
		t.Fatalf("create second durable reference: %v", err)
	}

	reboundAsset, err := assetRepo.Get(ctx, asset.ID)
	if err != nil {
		t.Fatalf("get rebound asset: %v", err)
	}
	if reboundAsset == nil || reboundAsset.OrphanedAt != nil {
		t.Fatalf("expected orphaned_at to be cleared, got %+v", reboundAsset)
	}
}

func TestDurableUploadRepoListStalePendingAssets(t *testing.T) {
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

	assetRepo := NewAssetRepo(pool)
	intentRepo := NewAssetUploadIntentRepo(pool)

	now := time.Now().UTC().Truncate(time.Microsecond)
	cutoff := now.Add(-20 * time.Minute)

	staleAsset, err := assetRepo.CreatePending(ctx, CreatePendingParams{
		Kind:           "archive",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "uploads/stale.zip",
		ContentType:    "application/zip",
		Metadata:       []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create stale pending asset: %v", err)
	}
	if _, err := intentRepo.Create(ctx, CreateAssetUploadIntentParams{
		AssetID:             staleAsset.ID,
		OwnerType:           "dataset",
		OwnerID:             uuid.New(),
		Role:                "attachment",
		IsPrimary:           false,
		DeclaredContentType: "application/zip",
		IdempotencyKey:      "stale-1",
		ExpiresAt:           now.Add(-10 * time.Minute),
	}); err != nil {
		t.Fatalf("create stale upload intent: %v", err)
	}
	if _, err := intentRepo.MarkExpired(ctx, MarkAssetUploadIntentExpiredParams{
		AssetID:   staleAsset.ID,
		ExpiredAt: now.Add(-5 * time.Minute),
	}); err != nil {
		t.Fatalf("mark stale intent expired: %v", err)
	}
	if _, err := sqlDB.ExecContext(ctx, `update asset set created_at = $2 where id = $1`, staleAsset.ID, now.Add(-30*time.Minute)); err != nil {
		t.Fatalf("backdate stale asset: %v", err)
	}

	liveAsset, err := assetRepo.CreatePending(ctx, CreatePendingParams{
		Kind:           "archive",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "uploads/live.zip",
		ContentType:    "application/zip",
		Metadata:       []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create live pending asset: %v", err)
	}
	if _, err := intentRepo.Create(ctx, CreateAssetUploadIntentParams{
		AssetID:             liveAsset.ID,
		OwnerType:           "dataset",
		OwnerID:             uuid.New(),
		Role:                "attachment",
		IsPrimary:           false,
		DeclaredContentType: "application/zip",
		IdempotencyKey:      "live-1",
		ExpiresAt:           now.Add(15 * time.Minute),
	}); err != nil {
		t.Fatalf("create live upload intent: %v", err)
	}
	if _, err := sqlDB.ExecContext(ctx, `update asset set created_at = $2 where id = $1`, liveAsset.ID, now.Add(-30*time.Minute)); err != nil {
		t.Fatalf("backdate live asset: %v", err)
	}

	staleAssets, err := assetRepo.ListStalePending(ctx, ListStalePendingAssetsParams{
		Now:    now,
		Cutoff: cutoff,
	})
	if err != nil {
		t.Fatalf("list stale pending assets: %v", err)
	}
	if len(staleAssets) != 1 || staleAssets[0].ID != staleAsset.ID {
		t.Fatalf("unexpected stale pending assets: %+v", staleAssets)
	}
}

func TestDurableUploadRepoDeleteAssetCascadesIntent(t *testing.T) {
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

	assetRepo := NewAssetRepo(pool)
	intentRepo := NewAssetUploadIntentRepo(pool)

	asset, err := assetRepo.CreatePending(ctx, CreatePendingParams{
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "raw/delete.png",
		ContentType:    "image/png",
		Metadata:       []byte(`{}`),
	})
	if err != nil {
		t.Fatalf("create pending asset: %v", err)
	}
	if _, err := intentRepo.Create(ctx, CreateAssetUploadIntentParams{
		AssetID:             asset.ID,
		OwnerType:           "dataset",
		OwnerID:             uuid.New(),
		Role:                "attachment",
		IsPrimary:           false,
		DeclaredContentType: "image/png",
		IdempotencyKey:      "delete-1",
		ExpiresAt:           time.Now().Add(15 * time.Minute).UTC(),
	}); err != nil {
		t.Fatalf("create upload intent: %v", err)
	}

	deleted, err := assetRepo.Delete(ctx, asset.ID)
	if err != nil {
		t.Fatalf("delete asset: %v", err)
	}
	if !deleted {
		t.Fatal("expected delete asset to report success")
	}

	intent, err := intentRepo.GetByAssetID(ctx, asset.ID)
	if err != nil {
		t.Fatalf("get intent after asset delete: %v", err)
	}
	if intent != nil {
		t.Fatalf("expected asset delete to cascade to intent, got %+v", intent)
	}
}

func TestDurableUploadRepoRetriesObjectKeyCollision(t *testing.T) {
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

	assetRepo := NewAssetRepo(pool)
	if _, err := assetRepo.CreatePending(ctx, CreatePendingParams{
		Kind:           "image",
		StorageBackend: "minio",
		Bucket:         "assets",
		ObjectKey:      "raw/collision.png",
		ContentType:    "image/png",
		Metadata:       []byte(`{}`),
	}); err != nil {
		t.Fatalf("seed colliding asset: %v", err)
	}

	txRunner := NewDurableUploadTxRunner(pool)

	var created *Asset
	err = txRunner.InTx(ctx, func(store DurableUploadTx) error {
		var err error
		created, err = store.CreatePendingAsset(ctx, CreatePendingAssetTxParams{
			Kind:           "image",
			StorageBackend: "minio",
			Bucket:         "assets",
			ContentType:    "image/png",
			Metadata:       []byte(`{}`),
			MaxAttempts:    3,
			BuildObjectKey: func(attempt int) string {
				if attempt == 0 {
					return "raw/collision.png"
				}
				return "raw/collision-2.png"
			},
		})
		return err
	})
	if err != nil {
		t.Fatalf("create pending asset with collision retry: %v", err)
	}
	if created == nil {
		t.Fatal("expected created asset after retry")
	}
	if got, want := created.ObjectKey, "raw/collision-2.png"; got != want {
		t.Fatalf("created object_key got %q want %q", got, want)
	}
}
