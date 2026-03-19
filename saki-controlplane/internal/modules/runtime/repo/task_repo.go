package repo

import (
	"context"
	"errors"
	"time"

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
var _ commands.PendingTaskClaimer = (*TaskRepo)(nil)
var _ commands.ClaimedTaskAssigner = (*TaskRepo)(nil)
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

func (r *TaskRepo) ClaimPendingTask(ctx context.Context) (*commands.PendingTask, error) {
	row, err := r.q.ClaimPendingTaskForAssignment(ctx)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return pendingTaskFromClaimRow(row), nil
}

func (r *TaskRepo) AssignClaimedTask(ctx context.Context, params commands.AssignClaimedTaskParams) (*commands.ClaimedTask, error) {
	row, err := r.q.AssignClaimedTask(ctx, sqlcdb.AssignClaimedTaskParams{
		ExecutionID:     nullableText(params.ExecutionID),
		AssignedAgentID: nullableText(params.AssignedAgentID),
		Attempt:         params.Attempt,
		LeaderEpoch:     nullableInt64(params.LeaderEpoch),
		ID:              params.TaskID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	return claimedTaskFromAssignClaimedRow(row), nil
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

// RequeueAssignedTasksWithoutAck 在一个 SQL 边界里同时回收 task / assignment / command，
// 避免 recovery 把任务改回 pending 后，旧 assign 命令还继续被投递。
func (r *TaskRepo) RequeueAssignedTasksWithoutAck(ctx context.Context, ackBefore time.Time) (int64, error) {
	return r.q.RequeueAssignedTasksWithoutAck(ctx, pgtype.Timestamptz{Time: ackBefore, Valid: true})
}

// FailRunningTasksForOfflineAgents 把失联 agent 上的运行中任务一次性推进到 failed，
// 同时收口同 assignment 上尚未结束的 command，避免 controlplane 继续等待不会到来的 agent 事件。
func (r *TaskRepo) FailRunningTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	_ = offlineBefore
	return r.q.FailRunningTasksForOfflineAgents(ctx)
}

// CancelRequestedTasksForOfflineAgents 在 agent 已失联时直接结束 cancel，
// 防止 task 永远卡在 cancel_requested，而 cancel command 还残留在可投递状态。
func (r *TaskRepo) CancelRequestedTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	_ = offlineBefore
	return r.q.CancelRequestedTasksForOfflineAgents(ctx)
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

func pendingTaskFromClaimRow(row sqlcdb.ClaimPendingTaskForAssignmentRow) *commands.PendingTask {
	return &commands.PendingTask{
		ID:               row.ID,
		TaskKind:         string(row.TaskKind),
		TaskType:         row.TaskType,
		Attempt:          row.Attempt,
		MaxAttempts:      row.MaxAttempts,
		ResolvedParams:   append([]byte(nil), row.ResolvedParams...),
		DependsOnTaskIDs: append([]uuid.UUID(nil), row.DependsOnTaskIds...),
		// 迁移阶段 runtime_task 仍没有 required_capabilities 列；
		// 这里先返回空集合，让 selector 只根据在线/容量做决策，后续再把业务声明落到 task 真相上。
		RequiredCapabilities: []string{},
	}
}

func claimedTaskFromAssignClaimedRow(row sqlcdb.AssignClaimedTaskRow) *commands.ClaimedTask {
	return &commands.ClaimedTask{
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
	}
}
