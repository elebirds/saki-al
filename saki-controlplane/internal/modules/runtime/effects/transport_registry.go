package effects

import (
	"context"
	"errors"
	"fmt"

	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

var ErrTransportNotConfigured = errors.New("command transport is not configured")

type CommandTransport interface {
	Mode() string
	DispatchAssign(ctx context.Context, cmd runtimerepo.AgentCommand) error
	DispatchCancel(ctx context.Context, cmd runtimerepo.AgentCommand) error
}

type TransportRegistry struct {
	byMode map[string]CommandTransport
}

func NewTransportRegistry(transports ...CommandTransport) *TransportRegistry {
	byMode := make(map[string]CommandTransport, len(transports))
	for _, transport := range transports {
		if transport == nil {
			continue
		}
		byMode[transport.Mode()] = transport
	}
	return &TransportRegistry{byMode: byMode}
}

func (r *TransportRegistry) DispatchAssign(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	transport, err := r.transportForMode(cmd.TransportMode)
	if err != nil {
		return err
	}
	return transport.DispatchAssign(ctx, cmd)
}

func (r *TransportRegistry) DispatchCancel(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	transport, err := r.transportForMode(cmd.TransportMode)
	if err != nil {
		return err
	}
	return transport.DispatchCancel(ctx, cmd)
}

func (r *TransportRegistry) transportForMode(mode string) (CommandTransport, error) {
	if r == nil {
		return nil, fmt.Errorf("%w: registry is nil", ErrTransportNotConfigured)
	}
	transport, ok := r.byMode[mode]
	if !ok {
		return nil, fmt.Errorf("%w: mode=%s", ErrTransportNotConfigured, mode)
	}
	return transport, nil
}
