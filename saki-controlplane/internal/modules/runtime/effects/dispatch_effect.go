package effects

import (
	"context"

	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

type DispatchEffect struct {
	transports *TransportRegistry
}

func NewDispatchEffect(transports *TransportRegistry) *DispatchEffect {
	return &DispatchEffect{transports: transports}
}

func (*DispatchEffect) CommandType() string {
	return "assign"
}

func (e *DispatchEffect) Apply(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	if cmd.CommandType != "assign" {
		return nil
	}
	return e.transports.DispatchAssign(ctx, cmd)
}
