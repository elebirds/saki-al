package effects

import (
	"context"

	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

type StopEffect struct {
	transports *TransportRegistry
}

func NewStopEffect(transports *TransportRegistry) *StopEffect {
	return &StopEffect{transports: transports}
}

func (*StopEffect) CommandType() string {
	return "cancel"
}

func (e *StopEffect) Apply(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	if cmd.CommandType != "cancel" {
		return nil
	}
	return e.transports.DispatchCancel(ctx, cmd)
}
