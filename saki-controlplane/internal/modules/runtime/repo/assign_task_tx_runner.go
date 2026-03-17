package repo

import (
	"context"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type AssignTaskTxRunner struct {
	tx *appdb.TxRunner
}

var _ commands.AssignTaskTxRunner = (*AssignTaskTxRunner)(nil)

func NewAssignTaskTxRunner(pool *pgxpool.Pool) *AssignTaskTxRunner {
	return &AssignTaskTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *AssignTaskTxRunner) InTx(ctx context.Context, fn func(store commands.AssignTaskTx) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)
		return fn(assignTaskTxStore{
			tasks:  newTaskRepo(q),
			outbox: newCommandOutboxWriter(newOutboxRepo(q)),
		})
	})
}

type assignTaskTxStore struct {
	tasks  *TaskRepo
	outbox *CommandOutboxWriter
}

func (s assignTaskTxStore) AssignPendingTask(ctx context.Context, params commands.AssignClaimParams) (*commands.ClaimedTask, error) {
	return s.tasks.AssignPendingTask(ctx, params)
}

func (s assignTaskTxStore) Append(ctx context.Context, event commands.OutboxEvent) error {
	return s.outbox.Append(ctx, event)
}
