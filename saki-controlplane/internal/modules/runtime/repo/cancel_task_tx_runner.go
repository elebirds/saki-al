package repo

import (
	"context"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type CancelTaskTxRunner struct {
	tx *appdb.TxRunner
}

var _ commands.CancelTaskTxRunner = (*CancelTaskTxRunner)(nil)

func NewCancelTaskTxRunner(pool *pgxpool.Pool) *CancelTaskTxRunner {
	return &CancelTaskTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *CancelTaskTxRunner) InTx(ctx context.Context, fn func(store commands.CancelTaskStore) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)
		return fn(cancelTaskTxStore{
			tasks:  newTaskRepo(q),
			outbox: newCommandOutboxWriter(newOutboxRepo(q)),
		})
	})
}

type cancelTaskTxStore struct {
	tasks  *TaskRepo
	outbox *CommandOutboxWriter
}

func (s cancelTaskTxStore) GetTask(ctx context.Context, taskID uuid.UUID) (*commands.TaskRecord, error) {
	return s.tasks.GetTask(ctx, taskID)
}

func (s cancelTaskTxStore) UpdateTask(ctx context.Context, update commands.TaskUpdate) error {
	return s.tasks.UpdateTask(ctx, update)
}

func (s cancelTaskTxStore) Append(ctx context.Context, event commands.OutboxEvent) error {
	return s.outbox.Append(ctx, event)
}
