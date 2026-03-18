package repo

import (
	"context"
	"errors"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

const assetObjectLocationUniqueConstraint = "asset_storage_backend_bucket_object_key_key"

type CreatePendingAssetTxParams struct {
	Kind           string
	StorageBackend string
	Bucket         string
	ContentType    string
	Metadata       []byte
	CreatedBy      *uuid.UUID
	BuildObjectKey func(attempt int) string
	MaxAttempts    int
}

type DurableUploadTx interface {
	CreatePendingAsset(ctx context.Context, params CreatePendingAssetTxParams) (*Asset, error)
	GetAsset(ctx context.Context, id uuid.UUID) (*Asset, error)
	MarkAssetReady(ctx context.Context, params MarkReadyParams) (*Asset, error)
	DeleteAsset(ctx context.Context, id uuid.UUID) (bool, error)
	ListStalePendingAssets(ctx context.Context, params ListStalePendingAssetsParams) ([]Asset, error)
	GetUploadIntentByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error)
	GetUploadIntentByOwnerKey(ctx context.Context, params GetAssetUploadIntentByOwnerKeyParams) (*AssetUploadIntent, error)
	CreateUploadIntent(ctx context.Context, params CreateAssetUploadIntentParams) (*AssetUploadIntent, error)
	MarkUploadIntentCompleted(ctx context.Context, params MarkAssetUploadIntentCompletedParams) (*AssetUploadIntent, error)
	MarkUploadIntentCanceled(ctx context.Context, params MarkAssetUploadIntentCanceledParams) (*AssetUploadIntent, error)
	MarkUploadIntentExpired(ctx context.Context, params MarkAssetUploadIntentExpiredParams) (*AssetUploadIntent, error)
	CreateDurableReference(ctx context.Context, params CreateAssetReferenceParams) (*AssetReference, error)
	ListActiveReferencesByOwner(ctx context.Context, params ListActiveReferencesByOwnerParams) ([]AssetReference, error)
}

type DurableUploadTxRunner struct {
	tx *appdb.TxRunner
}

func NewDurableUploadTxRunner(pool *pgxpool.Pool) *DurableUploadTxRunner {
	return &DurableUploadTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *DurableUploadTxRunner) InTx(ctx context.Context, fn func(store DurableUploadTx) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)
		return fn(durableUploadTxStore{
			tx:         tx,
			assets:     newAssetRepo(q),
			references: newAssetReferenceRepo(q),
			intents:    newAssetUploadIntentRepo(q),
		})
	})
}

type durableUploadTxStore struct {
	tx         pgx.Tx
	assets     *AssetRepo
	references *AssetReferenceRepo
	intents    *AssetUploadIntentRepo
}

func (s durableUploadTxStore) CreatePendingAsset(ctx context.Context, params CreatePendingAssetTxParams) (*Asset, error) {
	if params.BuildObjectKey == nil {
		return nil, errors.New("build object key is required")
	}

	maxAttempts := params.MaxAttempts
	if maxAttempts <= 0 {
		maxAttempts = 1
	}

	var lastErr error
	for attempt := 0; attempt < maxAttempts; attempt++ {
		savepoint, err := s.tx.Begin(ctx)
		if err != nil {
			return nil, err
		}

		asset, err := newAssetRepo(sqlcdb.New(savepoint)).CreatePending(ctx, CreatePendingParams{
			Kind:           params.Kind,
			StorageBackend: params.StorageBackend,
			Bucket:         params.Bucket,
			ObjectKey:      params.BuildObjectKey(attempt),
			ContentType:    params.ContentType,
			Metadata:       params.Metadata,
			CreatedBy:      params.CreatedBy,
		})
		if err == nil {
			if err := savepoint.Commit(ctx); err != nil {
				return nil, err
			}
			return asset, nil
		}
		_ = savepoint.Rollback(ctx)
		if !isAssetObjectKeyCollision(err) {
			return nil, err
		}
		lastErr = err
	}

	return nil, lastErr
}

func (s durableUploadTxStore) GetAsset(ctx context.Context, id uuid.UUID) (*Asset, error) {
	return s.assets.Get(ctx, id)
}

func (s durableUploadTxStore) MarkAssetReady(ctx context.Context, params MarkReadyParams) (*Asset, error) {
	return s.assets.MarkReady(ctx, params)
}

func (s durableUploadTxStore) DeleteAsset(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.assets.Delete(ctx, id)
}

func (s durableUploadTxStore) ListStalePendingAssets(ctx context.Context, params ListStalePendingAssetsParams) ([]Asset, error) {
	return s.assets.ListStalePending(ctx, params)
}

func (s durableUploadTxStore) GetUploadIntentByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error) {
	return s.intents.GetByAssetID(ctx, assetID)
}

func (s durableUploadTxStore) GetUploadIntentByOwnerKey(ctx context.Context, params GetAssetUploadIntentByOwnerKeyParams) (*AssetUploadIntent, error) {
	return s.intents.GetByOwnerKey(ctx, params)
}

func (s durableUploadTxStore) CreateUploadIntent(ctx context.Context, params CreateAssetUploadIntentParams) (*AssetUploadIntent, error) {
	return s.intents.Create(ctx, params)
}

func (s durableUploadTxStore) MarkUploadIntentCompleted(ctx context.Context, params MarkAssetUploadIntentCompletedParams) (*AssetUploadIntent, error) {
	return s.intents.MarkCompleted(ctx, params)
}

func (s durableUploadTxStore) MarkUploadIntentCanceled(ctx context.Context, params MarkAssetUploadIntentCanceledParams) (*AssetUploadIntent, error) {
	return s.intents.MarkCanceled(ctx, params)
}

func (s durableUploadTxStore) MarkUploadIntentExpired(ctx context.Context, params MarkAssetUploadIntentExpiredParams) (*AssetUploadIntent, error) {
	return s.intents.MarkExpired(ctx, params)
}

func (s durableUploadTxStore) CreateDurableReference(ctx context.Context, params CreateAssetReferenceParams) (*AssetReference, error) {
	return s.references.CreateDurable(ctx, params)
}

func (s durableUploadTxStore) ListActiveReferencesByOwner(ctx context.Context, params ListActiveReferencesByOwnerParams) ([]AssetReference, error) {
	return s.references.ListActiveByOwner(ctx, params)
}

func isAssetObjectKeyCollision(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) &&
		pgErr.Code == "23505" &&
		pgErr.ConstraintName == assetObjectLocationUniqueConstraint
}
