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
			tasks:       newTaskRepo(q),
			assignments: newTaskAssignmentRepo(q),
			agents:      newAgentRepo(q),
			commands:    newAgentCommandRepo(q),
		})
	})
}

type cancelTaskTxStore struct {
	tasks       *TaskRepo
	assignments *TaskAssignmentRepo
	agents      *AgentRepo
	commands    *AgentCommandRepo
}

func (s cancelTaskTxStore) GetTask(ctx context.Context, taskID uuid.UUID) (*commands.TaskRecord, error) {
	return s.tasks.GetTask(ctx, taskID)
}

func (s cancelTaskTxStore) UpdateTask(ctx context.Context, update commands.TaskUpdate) error {
	return s.tasks.UpdateTask(ctx, update)
}

func (s cancelTaskTxStore) GetTaskAssignmentByExecutionID(ctx context.Context, executionID string) (*commands.TaskAssignmentRecord, error) {
	assignment, err := s.assignments.GetByExecutionID(ctx, executionID)
	if err != nil {
		return nil, err
	}
	if assignment == nil {
		return nil, nil
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

func (s cancelTaskTxStore) GetAgentByID(ctx context.Context, agentID string) (*commands.AgentRecord, error) {
	agent, err := s.agents.GetByID(ctx, agentID)
	if err != nil {
		return nil, err
	}
	return commandsAgentFromRepo(agent), nil
}

func (s cancelTaskTxStore) AppendCancelCommand(ctx context.Context, params commands.AppendCancelTaskCommandParams) error {
	_, err := s.commands.AppendCancel(ctx, AppendCancelCommandParams{
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
