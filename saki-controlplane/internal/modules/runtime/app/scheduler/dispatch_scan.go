package scheduler

import "context"

type DispatchCommand struct {
	LeaderEpoch int64
}

type Assigner interface {
	Dispatch(ctx context.Context, command DispatchCommand) error
}
