package effects

import (
	"context"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type EventBroadcaster interface {
	Publish(ctx context.Context, event commands.OutboxEvent) error
}

type StreamEffect struct {
	broadcaster EventBroadcaster
}

func NewStreamEffect(broadcaster EventBroadcaster) *StreamEffect {
	return &StreamEffect{broadcaster: broadcaster}
}

func (e *StreamEffect) Apply(ctx context.Context, event commands.OutboxEvent) error {
	if e.broadcaster == nil {
		return nil
	}
	return e.broadcaster.Publish(ctx, event)
}
