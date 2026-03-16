package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type RuntimeTask struct {
	ID          uuid.UUID
	TaskType    string
	Status      string
	ClaimedBy   *string
	ClaimedAt   *time.Time
	LeaderEpoch *int64
}

type CreateTaskParams struct {
	ID       uuid.UUID
	TaskType string
}

type ClaimTaskParams struct {
	ClaimedBy   string
	LeaderEpoch int64
}

type TaskRepo struct {
	q *sqlcdb.Queries
}

func NewTaskRepo(pool *pgxpool.Pool) *TaskRepo {
	return &TaskRepo{q: sqlcdb.New(pool)}
}

func (r *TaskRepo) CreateTask(ctx context.Context, params CreateTaskParams) error {
	_, err := r.q.CreateRuntimeTask(ctx, sqlcdb.CreateRuntimeTaskParams{
		ID:       params.ID,
		TaskType: params.TaskType,
	})
	return err
}

func (r *TaskRepo) ClaimPendingTask(ctx context.Context, params ClaimTaskParams) (*RuntimeTask, error) {
	row, err := r.q.ClaimPendingTask(ctx, sqlcdb.ClaimPendingTaskParams{
		ClaimedBy:   pgtype.Text{String: params.ClaimedBy, Valid: true},
		LeaderEpoch: pgtype.Int8{Int64: params.LeaderEpoch, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	return &RuntimeTask{
		ID:          row.ID,
		TaskType:    row.TaskType,
		Status:      row.Status,
		ClaimedBy:   optionalText(row.ClaimedBy),
		ClaimedAt:   optionalTime(row.ClaimedAt),
		LeaderEpoch: optionalInt64(row.LeaderEpoch),
	}, nil
}

func optionalText(value pgtype.Text) *string {
	if !value.Valid {
		return nil
	}
	text := value.String
	return &text
}

func optionalTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	ts := value.Time
	return &ts
}

func optionalInt64(value pgtype.Int8) *int64 {
	if !value.Valid {
		return nil
	}
	n := value.Int64
	return &n
}
