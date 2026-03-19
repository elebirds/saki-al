package scheduler

import (
	"context"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type DispatchCommand struct {
	LeaderEpoch int64
}

type DispatchTaskAssigner interface {
	Handle(ctx context.Context, cmd commands.AssignTaskCommand) (*commands.AssignResult, error)
}

type Assigner interface {
	Dispatch(ctx context.Context, command DispatchCommand) error
}

type DispatchScan struct {
	assigner DispatchTaskAssigner
}

func NewDispatchScan(assigner DispatchTaskAssigner) *DispatchScan {
	return &DispatchScan{
		assigner: assigner,
	}
}

func (s *DispatchScan) Dispatch(ctx context.Context, command DispatchCommand) error {
	if s == nil || s.assigner == nil {
		return nil
	}

	_, err := s.assigner.Handle(ctx, commands.AssignTaskCommand{
		LeaderEpoch: command.LeaderEpoch,
	})
	return err
}
