package repo

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type RuntimeTask struct {
	ID                 uuid.UUID
	TaskKind           string
	TaskType           string
	Status             string
	CurrentExecutionID *string
	AssignedAgentID    *string
	Attempt            int32
	MaxAttempts        int32
	ResolvedParams     []byte
	DependsOnTaskIDs   []uuid.UUID
	LeaderEpoch        *int64
}

type CreateTaskParams struct {
	ID       uuid.UUID
	TaskKind string
	TaskType string
}

type AssignTaskParams struct {
	AssignedAgentID string
	LeaderEpoch     int64
}

type ClaimTaskParams struct {
	ClaimedBy   string
	LeaderEpoch int64
}

type RuntimeSummary struct {
	PendingTasks int32
	RunningTasks int32
	LeaderEpoch  int64
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
		TaskKind: taskKindOrDefault(params.TaskKind),
		TaskType: params.TaskType,
	})
	return err
}

func (r *TaskRepo) AssignPendingTask(ctx context.Context, params AssignTaskParams) (*RuntimeTask, error) {
	row, err := r.q.AssignPendingTask(ctx, sqlcdb.AssignPendingTaskParams{
		AssignedAgentID: pgtype.Text{String: params.AssignedAgentID, Valid: true},
		LeaderEpoch:     pgtype.Int8{Int64: params.LeaderEpoch, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	return runtimeTaskFromAssignedRow(row), nil
}

func (r *TaskRepo) ClaimPendingTask(ctx context.Context, params ClaimTaskParams) (*RuntimeTask, error) {
	return r.AssignPendingTask(ctx, AssignTaskParams{
		AssignedAgentID: params.ClaimedBy,
		LeaderEpoch:     params.LeaderEpoch,
	})
}

func (r *TaskRepo) GetTask(ctx context.Context, taskID uuid.UUID) (*commands.TaskRecord, error) {
	row, err := r.q.GetRuntimeTask(ctx, taskID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return &commands.TaskRecord{
		ID:          row.ID,
		TaskType:    row.TaskType,
		Status:      row.Status,
		ClaimedBy:   textValue(row.AssignedAgentID),
		LeaderEpoch: int64Value(row.LeaderEpoch),
	}, nil
}

func (r *TaskRepo) UpdateTask(ctx context.Context, update commands.TaskUpdate) error {
	return r.q.UpdateRuntimeTask(ctx, sqlcdb.UpdateRuntimeTaskParams{
		ID:              update.ID,
		Status:          update.Status,
		AssignedAgentID: nullableText(update.ClaimedBy),
		LeaderEpoch:     nullableInt64(update.LeaderEpoch),
	})
}

func (r *TaskRepo) GetSummary(ctx context.Context) (RuntimeSummary, error) {
	row, err := r.q.GetRuntimeSummary(ctx)
	if err != nil {
		return RuntimeSummary{}, err
	}

	return RuntimeSummary{
		PendingTasks: row.PendingTasks,
		RunningTasks: row.RunningTasks,
		LeaderEpoch:  row.LeaderEpoch,
	}, nil
}

func optionalText(value pgtype.Text) *string {
	if !value.Valid {
		return nil
	}
	text := value.String
	return &text
}

func optionalInt64(value pgtype.Int8) *int64 {
	if !value.Valid {
		return nil
	}
	n := value.Int64
	return &n
}

func textValue(value pgtype.Text) string {
	if !value.Valid {
		return ""
	}
	return value.String
}

func int64Value(value pgtype.Int8) int64 {
	if !value.Valid {
		return 0
	}
	return value.Int64
}

func nullableText(value string) pgtype.Text {
	if value == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: value, Valid: true}
}

func nullableInt64(value int64) pgtype.Int8 {
	if value == 0 {
		return pgtype.Int8{}
	}
	return pgtype.Int8{Int64: value, Valid: true}
}

func taskKindOrDefault(taskKind string) string {
	if taskKind == "" {
		return "PREDICTION"
	}
	return taskKind
}

func runtimeTaskFromAssignedRow(row sqlcdb.AssignPendingTaskRow) *RuntimeTask {
	return &RuntimeTask{
		ID:                 row.ID,
		TaskKind:           row.TaskKind,
		TaskType:           row.TaskType,
		Status:             row.Status,
		CurrentExecutionID: optionalText(row.CurrentExecutionID),
		AssignedAgentID:    optionalText(row.AssignedAgentID),
		Attempt:            row.Attempt,
		MaxAttempts:        row.MaxAttempts,
		ResolvedParams:     row.ResolvedParams,
		DependsOnTaskIDs:   row.DependsOnTaskIds,
		LeaderEpoch:        optionalInt64(row.LeaderEpoch),
	}
}

func runtimeTaskFromRow(row sqlcdb.RuntimeTask) *RuntimeTask {
	return &RuntimeTask{
		ID:                 row.ID,
		TaskKind:           row.TaskKind,
		TaskType:           row.TaskType,
		Status:             row.Status,
		CurrentExecutionID: optionalText(row.CurrentExecutionID),
		AssignedAgentID:    optionalText(row.AssignedAgentID),
		Attempt:            row.Attempt,
		MaxAttempts:        row.MaxAttempts,
		ResolvedParams:     row.ResolvedParams,
		DependsOnTaskIDs:   row.DependsOnTaskIds,
		LeaderEpoch:        optionalInt64(row.LeaderEpoch),
	}
}
