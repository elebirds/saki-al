package repo

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type TaskAssignment struct {
	ID          int64
	TaskID      uuid.UUID
	Attempt     int32
	AgentID     string
	ExecutionID string
	Status      string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

type CreateTaskAssignmentParams struct {
	TaskID      uuid.UUID
	Attempt     int32
	AgentID     string
	ExecutionID string
	Status      string
}

// TaskAssignmentRepo 把一次派发独立持久化，恢复逻辑只需要围绕 assignment 继续推进即可。
type TaskAssignmentRepo struct {
	q *sqlcdb.Queries
}

func NewTaskAssignmentRepo(pool *pgxpool.Pool) *TaskAssignmentRepo {
	return newTaskAssignmentRepo(sqlcdb.New(pool))
}

func newTaskAssignmentRepo(q *sqlcdb.Queries) *TaskAssignmentRepo {
	return &TaskAssignmentRepo{q: q}
}

func (r *TaskAssignmentRepo) Create(ctx context.Context, params CreateTaskAssignmentParams) (*TaskAssignment, error) {
	row, err := r.q.CreateTaskAssignment(ctx, sqlcdb.CreateTaskAssignmentParams{
		TaskID:      params.TaskID,
		Attempt:     params.Attempt,
		AgentID:     params.AgentID,
		ExecutionID: params.ExecutionID,
		Status:      runtimeTaskStatus(params.Status),
	})
	if err != nil {
		return nil, err
	}
	return taskAssignmentFromModel(row), nil
}

func (r *TaskAssignmentRepo) GetByExecutionID(ctx context.Context, executionID string) (*TaskAssignment, error) {
	row, err := r.q.GetTaskAssignmentByExecutionID(ctx, executionID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return taskAssignmentFromModel(row), nil
}

func taskAssignmentFromModel(row sqlcdb.TaskAssignment) *TaskAssignment {
	return &TaskAssignment{
		ID:          row.ID,
		TaskID:      row.TaskID,
		Attempt:     row.Attempt,
		AgentID:     row.AgentID,
		ExecutionID: row.ExecutionID,
		Status:      string(row.Status),
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
