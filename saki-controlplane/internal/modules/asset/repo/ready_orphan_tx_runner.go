package repo

import (
	"context"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type ReadyOrphanGCTx interface {
	LockReadyOrphanedAsset(ctx context.Context, id uuid.UUID, cutoff time.Time) (*Asset, error)
	DeleteAsset(ctx context.Context, id uuid.UUID) (bool, error)
}

type ReadyOrphanGCTxRunner struct {
	tx *appdb.TxRunner
}

func NewReadyOrphanGCTxRunner(pool *pgxpool.Pool) *ReadyOrphanGCTxRunner {
	return &ReadyOrphanGCTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *ReadyOrphanGCTxRunner) InTx(ctx context.Context, fn func(store ReadyOrphanGCTx) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		return fn(readyOrphanGCTxStore{
			assets: newAssetRepo(sqlcdb.New(tx)),
		})
	})
}

type readyOrphanGCTxStore struct {
	assets *AssetRepo
}

func (s readyOrphanGCTxStore) LockReadyOrphanedAsset(ctx context.Context, id uuid.UUID, cutoff time.Time) (*Asset, error) {
	return s.assets.GetReadyOrphanedForUpdate(ctx, GetReadyOrphanedAssetForUpdateParams{
		ID:     id,
		Cutoff: cutoff,
	})
}

func (s readyOrphanGCTxStore) DeleteAsset(ctx context.Context, id uuid.UUID) (bool, error) {
	return s.assets.Delete(ctx, id)
}
