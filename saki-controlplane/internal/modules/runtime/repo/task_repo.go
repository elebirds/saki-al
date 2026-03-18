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

type CreateTaskParams struct {
	ID       uuid.UUID
	TaskKind string
	TaskType string
}

type AssignTaskParams = commands.AssignClaimParams

type RuntimeSummary struct {
	PendingTasks int32
	RunningTasks int32
	LeaderEpoch  int64
}

type TaskRepo struct {
	q *sqlcdb.Queries
}

var _ commands.TaskClaimer = (*TaskRepo)(nil)
var _ commands.ExecutionScopedTaskStore = (*TaskRepo)(nil)

func NewTaskRepo(pool *pgxpool.Pool) *TaskRepo {
	return newTaskRepo(sqlcdb.New(pool))
}

func newTaskRepo(q *sqlcdb.Queries) *TaskRepo {
	return &TaskRepo{q: q}
}

func (r *TaskRepo) CreateTask(ctx context.Context, params CreateTaskParams) error {
	_, err := r.q.CreateRuntimeTask(ctx, sqlcdb.CreateRuntimeTaskParams{
		ID:       params.ID,
		TaskKind: taskKindOrDefault(params.TaskKind),
		TaskType: params.TaskType,
	})
	return err
}

func (r *TaskRepo) AssignPendingTask(ctx context.Context, params AssignTaskParams) (*commands.ClaimedTask, error) {
	row, err := r.q.AssignPendingTask(ctx, sqlcdb.AssignPendingTaskParams{
		AssignedAgentID: pgtype.Text{String: params.AssignedAgentID, Valid: true},
		LeaderEpoch:     pgtype.Int8{Int64: params.LeaderEpoch, Valid: true},
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return claimedTaskFromAssignedRow(row), nil
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
		ID:                 row.ID,
		TaskKind:           string(row.TaskKind),
		TaskType:           row.TaskType,
		Status:             string(row.Status),
		CurrentExecutionID: textValue(row.CurrentExecutionID),
		AssignedAgentID:    textValue(row.AssignedAgentID),
		Attempt:            row.Attempt,
		MaxAttempts:        row.MaxAttempts,
		ResolvedParams:     append([]byte(nil), row.ResolvedParams...),
		DependsOnTaskIDs:   append([]uuid.UUID(nil), row.DependsOnTaskIds...),
		LeaderEpoch:        int64Value(row.LeaderEpoch),
	}, nil
}

func (r *TaskRepo) AdvanceTaskByExecution(ctx context.Context, params commands.AdvanceTaskByExecutionParams) (*commands.TaskRecord, error) {
	row, err := r.q.AdvanceRuntimeTaskByExecution(ctx, sqlcdb.AdvanceRuntimeTaskByExecutionParams{
		ToStatus:     runtimeTaskStatus(params.ToStatus),
		ID:           params.ID,
		ExecutionID:  nullableText(params.ExecutionID),
		FromStatuses: runtimeTaskStatuses(params.FromStatuses),
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return &commands.TaskRecord{
		ID:                 row.ID,
		TaskKind:           string(row.TaskKind),
		TaskType:           row.TaskType,
		Status:             string(row.Status),
		CurrentExecutionID: textValue(row.CurrentExecutionID),
		AssignedAgentID:    textValue(row.AssignedAgentID),
		Attempt:            row.Attempt,
		MaxAttempts:        row.MaxAttempts,
		ResolvedParams:     append([]byte(nil), row.ResolvedParams...),
		DependsOnTaskIDs:   append([]uuid.UUID(nil), row.DependsOnTaskIds...),
		LeaderEpoch:        int64Value(row.LeaderEpoch),
	}, nil
}

func (r *TaskRepo) UpdateTask(ctx context.Context, update commands.TaskUpdate) error {
	return r.q.UpdateRuntimeTask(ctx, sqlcdb.UpdateRuntimeTaskParams{
		ID:              update.ID,
		Status:          runtimeTaskStatus(update.Status),
		AssignedAgentID: nullableText(update.AssignedAgentID),
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

func taskKindOrDefault(taskKind string) sqlcdb.RuntimeTaskKind {
	if taskKind == "" {
		return sqlcdb.RuntimeTaskKindPREDICTION
	}
	return sqlcdb.RuntimeTaskKind(taskKind)
}

func runtimeTaskStatus(status string) sqlcdb.RuntimeTaskStatus {
	return sqlcdb.RuntimeTaskStatus(status)
}

func runtimeTaskStatuses(statuses []string) []sqlcdb.RuntimeTaskStatus {
	items := make([]sqlcdb.RuntimeTaskStatus, 0, len(statuses))
	for _, status := range statuses {
		items = append(items, runtimeTaskStatus(status))
	}
	return items
}

func claimedTaskFromAssignedRow(row sqlcdb.AssignPendingTaskRow) *commands.ClaimedTask {
	return &commands.ClaimedTask{
		ID:                 row.ID,
		TaskKind:           string(row.TaskKind),
		TaskType:           row.TaskType,
		Status:             string(row.Status),
		CurrentExecutionID: textValue(row.CurrentExecutionID),
		AssignedAgentID:    textValue(row.AssignedAgentID),
		Attempt:            row.Attempt,
		MaxAttempts:        row.MaxAttempts,
		ResolvedParams:     row.ResolvedParams,
		DependsOnTaskIDs:   row.DependsOnTaskIds,
		LeaderEpoch:        int64Value(row.LeaderEpoch),
	}
}
