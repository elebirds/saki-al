package scheduler

import (
	"context"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type DispatchCommand struct {
	LeaderEpoch int64
}

type DispatchTaskAssigner interface {
	Handle(ctx context.Context, cmd commands.AssignTaskCommand) (*commands.TaskRecord, error)
}

type Assigner interface {
	Dispatch(ctx context.Context, command DispatchCommand) error
}

type DispatchScan struct {
	assigner      DispatchTaskAssigner
	targetAgentID string
}

func NewDispatchScan(assigner DispatchTaskAssigner, targetAgentID string) *DispatchScan {
	return &DispatchScan{
		assigner:      assigner,
		targetAgentID: targetAgentID,
	}
}

func (s *DispatchScan) Dispatch(ctx context.Context, command DispatchCommand) error {
	_, err := s.assigner.Handle(ctx, commands.AssignTaskCommand{
		AssignedAgentID: s.targetAgentID,
		LeaderEpoch:     command.LeaderEpoch,
	})
	return err
}
