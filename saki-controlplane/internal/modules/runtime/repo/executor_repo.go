package repo

import (
	"context"
	"slices"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type RuntimeExecutor struct {
	ID           string
	Version      string
	Capabilities []string
	Status       string
	LastSeenAt   time.Time
}

type ExecutorRepo struct {
	q *sqlcdb.Queries
}

func NewExecutorRepo(pool *pgxpool.Pool) *ExecutorRepo {
	return &ExecutorRepo{q: sqlcdb.New(pool)}
}

func (r *ExecutorRepo) Register(ctx context.Context, executor commands.ExecutorRecord) (*commands.ExecutorRecord, error) {
	capabilities := normalizeExecutorCapabilities(executor.Capabilities)

	row, err := r.q.RegisterRuntimeExecutor(ctx, sqlcdb.RegisterRuntimeExecutorParams{
		ID:           executor.ID,
		Version:      executor.Version,
		Capabilities: capabilities,
		LastSeenAt:   pgtype.Timestamptz{Time: executor.LastSeenAt, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	return &commands.ExecutorRecord{
		ID:           row.ID,
		Version:      row.Version,
		Capabilities: normalizeExecutorCapabilities(row.Capabilities),
		LastSeenAt:   row.LastSeenAt.Time,
	}, nil
}

func (r *ExecutorRepo) Heartbeat(ctx context.Context, executorID string, seenAt time.Time) error {
	_, err := r.q.HeartbeatRuntimeExecutor(ctx, sqlcdb.HeartbeatRuntimeExecutorParams{
		ID:         executorID,
		LastSeenAt: pgtype.Timestamptz{Time: seenAt, Valid: true},
	})
	return err
}

func (r *ExecutorRepo) List(ctx context.Context) ([]RuntimeExecutor, error) {
	rows, err := r.q.ListRuntimeExecutors(ctx)
	if err != nil {
		return nil, err
	}

	executors := make([]RuntimeExecutor, 0, len(rows))
	for _, row := range rows {
		executors = append(executors, RuntimeExecutor{
			ID:           row.ID,
			Version:      row.Version,
			Capabilities: normalizeExecutorCapabilities(row.Capabilities),
			Status:       string(row.Status),
			LastSeenAt:   row.LastSeenAt.Time,
		})
	}

	return executors, nil
}

func normalizeExecutorCapabilities(capabilities []string) []string {
	if capabilities == nil {
		return []string{}
	}
	return slices.Clone(capabilities)
}
