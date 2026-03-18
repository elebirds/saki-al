package repo

import (
	"context"
	"errors"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type ImportTask struct {
	ID           uuid.UUID
	UserID       uuid.UUID
	Mode         string
	ResourceType string
	ResourceID   uuid.UUID
	Status       string
	Payload      []byte
	Result       []byte
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

type ImportTaskEvent struct {
	Seq       int64
	TaskID    uuid.UUID
	Event     string
	Phase     string
	Payload   []byte
	CreatedAt time.Time
}

type CreateTaskParams struct {
	ID           uuid.UUID
	UserID       uuid.UUID
	Mode         string
	ResourceType string
	ResourceID   uuid.UUID
	Payload      []byte
}

type AppendTaskEventParams struct {
	TaskID  uuid.UUID
	Event   string
	Phase   string
	Payload []byte
}

type TaskRepo struct {
	q *sqlcdb.Queries
}

func NewTaskRepo(pool *pgxpool.Pool) *TaskRepo {
	return &TaskRepo{q: sqlcdb.New(pool)}
}

func (r *TaskRepo) Create(ctx context.Context, params CreateTaskParams) (*ImportTask, error) {
	row, err := r.q.CreateImportTask(ctx, sqlcdb.CreateImportTaskParams{
		ID:           params.ID,
		UserID:       params.UserID,
		Mode:         params.Mode,
		ResourceType: params.ResourceType,
		ResourceID:   params.ResourceID,
		Payload:      params.Payload,
	})
	if err != nil {
		return nil, err
	}
	return mapImportTask(row), nil
}

func (r *TaskRepo) Get(ctx context.Context, id uuid.UUID) (*ImportTask, error) {
	row, err := r.q.GetImportTask(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapImportTask(row), nil
}

func (r *TaskRepo) MarkRunning(ctx context.Context, taskID uuid.UUID) error {
	return r.q.MarkImportTaskRunning(ctx, taskID)
}

func (r *TaskRepo) MarkCompleted(ctx context.Context, taskID uuid.UUID, result []byte) error {
	return r.q.MarkImportTaskCompleted(ctx, sqlcdb.MarkImportTaskCompletedParams{
		ID:     taskID,
		Result: result,
	})
}

func (r *TaskRepo) MarkFailed(ctx context.Context, taskID uuid.UUID, result []byte) error {
	return r.q.MarkImportTaskFailed(ctx, sqlcdb.MarkImportTaskFailedParams{
		ID:     taskID,
		Result: result,
	})
}

func (r *TaskRepo) AppendEvent(ctx context.Context, params AppendTaskEventParams) (*ImportTaskEvent, error) {
	row, err := r.q.AppendImportTaskEvent(ctx, sqlcdb.AppendImportTaskEventParams{
		TaskID:  params.TaskID,
		Event:   params.Event,
		Phase:   importTaskEventPhase(params.Phase),
		Payload: params.Payload,
	})
	if err != nil {
		return nil, err
	}
	return &ImportTaskEvent{
		Seq:       row.Seq,
		TaskID:    row.TaskID,
		Event:     row.Event,
		Phase:     string(row.Phase),
		Payload:   row.Payload,
		CreatedAt: row.CreatedAt.Time,
	}, nil
}

func (r *TaskRepo) ListEventsAfter(ctx context.Context, taskID uuid.UUID, afterSeq int64, limit int32) ([]ImportTaskEvent, error) {
	rows, err := r.q.ListImportTaskEventsAfter(ctx, sqlcdb.ListImportTaskEventsAfterParams{
		TaskID:     taskID,
		AfterSeq:   afterSeq,
		LimitCount: limit,
	})
	if err != nil {
		return nil, err
	}
	events := make([]ImportTaskEvent, 0, len(rows))
	for _, row := range rows {
		events = append(events, ImportTaskEvent{
			Seq:       row.Seq,
			TaskID:    row.TaskID,
			Event:     row.Event,
			Phase:     string(row.Phase),
			Payload:   row.Payload,
			CreatedAt: row.CreatedAt.Time,
		})
	}
	return events, nil
}

func mapImportTask(row sqlcdb.ImportTask) *ImportTask {
	return &ImportTask{
		ID:           row.ID,
		UserID:       row.UserID,
		Mode:         row.Mode,
		ResourceType: row.ResourceType,
		ResourceID:   row.ResourceID,
		Status:       string(row.Status),
		Payload:      row.Payload,
		Result:       row.Result,
		CreatedAt:    row.CreatedAt.Time,
		UpdatedAt:    row.UpdatedAt.Time,
	}
}

func importTaskEventPhase(phase string) sqlcdb.ImportTaskEventPhase {
	return sqlcdb.ImportTaskEventPhase(phase)
}
