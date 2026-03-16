package effects

import (
	"context"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type ReadModelProjector interface {
	Project(ctx context.Context, event commands.OutboxEvent) error
}

type ReadModelEffect struct {
	projector ReadModelProjector
}

func NewReadModelEffect(projector ReadModelProjector) *ReadModelEffect {
	return &ReadModelEffect{projector: projector}
}

func (e *ReadModelEffect) Apply(ctx context.Context, event commands.OutboxEvent) error {
	if e.projector == nil {
		return nil
	}
	return e.projector.Project(ctx, event)
}
