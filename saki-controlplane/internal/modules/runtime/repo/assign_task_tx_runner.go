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
		// assign 主链路在一个事务里同时碰 task/agent/assignment/command/outbox，
		// 这样迁移窗口里不会出现“任务状态、agent_command、兼容 outbox”三边不一致。
		return fn(assignTaskTxStore{
			tasks:       newTaskRepo(q),
			agents:      newAgentRepo(q),
			assignments: newTaskAssignmentRepo(q),
			commands:    newAgentCommandRepo(q),
			outbox:      newCommandOutboxWriter(newOutboxRepo(q)),
		})
	})
}

type assignTaskTxStore struct {
	tasks       *TaskRepo
	agents      *AgentRepo
	assignments *TaskAssignmentRepo
	commands    *AgentCommandRepo
	outbox      *CommandOutboxWriter
}

func (s assignTaskTxStore) ClaimPendingTask(ctx context.Context) (*commands.PendingTask, error) {
	return s.tasks.ClaimPendingTask(ctx)
}

func (s assignTaskTxStore) ListAssignableAgents(ctx context.Context) ([]commands.AgentRecord, error) {
	agents, err := s.agents.List(ctx)
	if err != nil {
		return nil, err
	}

	items := make([]commands.AgentRecord, 0, len(agents))
	for _, agent := range agents {
		items = append(items, *commandsAgentFromRepo(&agent))
	}
	return items, nil
}

func (s assignTaskTxStore) CreateTaskAssignment(ctx context.Context, params commands.CreateTaskAssignmentParams) (*commands.TaskAssignmentRecord, error) {
	assignment, err := s.assignments.Create(ctx, CreateTaskAssignmentParams{
		TaskID:      params.TaskID,
		Attempt:     params.Attempt,
		AgentID:     params.AgentID,
		ExecutionID: params.ExecutionID,
		Status:      params.Status,
	})
	if err != nil {
		return nil, err
	}

	return &commands.TaskAssignmentRecord{
		ID:          assignment.ID,
		TaskID:      assignment.TaskID,
		Attempt:     assignment.Attempt,
		AgentID:     assignment.AgentID,
		ExecutionID: assignment.ExecutionID,
		Status:      assignment.Status,
	}, nil
}

func (s assignTaskTxStore) AssignClaimedTask(ctx context.Context, params commands.AssignClaimedTaskParams) (*commands.ClaimedTask, error) {
	return s.tasks.AssignClaimedTask(ctx, params)
}

func (s assignTaskTxStore) AppendAssignCommand(ctx context.Context, params commands.AppendAssignTaskCommandParams) error {
	_, err := s.commands.AppendAssign(ctx, AppendAssignCommandParams{
		CommandID:     params.CommandID,
		AgentID:       params.AgentID,
		TaskID:        params.TaskID,
		AssignmentID:  params.AssignmentID,
		TransportMode: params.TransportMode,
		Payload:       params.Payload,
		AvailableAt:   params.AvailableAt,
		ExpireAt:      params.ExpireAt,
	})
	return err
}

func (s assignTaskTxStore) Append(ctx context.Context, event commands.OutboxEvent) error {
	return s.outbox.Append(ctx, event)
}
