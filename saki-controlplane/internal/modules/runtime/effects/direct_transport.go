package effects

import (
	"context"
	"encoding/json"
	"fmt"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

type AgentLookupStore interface {
	GetByID(ctx context.Context, agentID string) (*runtimerepo.Agent, error)
}

type AgentControlClient interface {
	AssignTask(ctx context.Context, req *runtimev1.AssignTaskRequest) error
	StopTask(ctx context.Context, req *runtimev1.StopTaskRequest) error
}

type AgentControlClientFactory interface {
	New(baseURL string) AgentControlClient
}

type AgentControlClientFactoryFunc func(baseURL string) AgentControlClient

func (f AgentControlClientFactoryFunc) New(baseURL string) AgentControlClient {
	return f(baseURL)
}

type DirectTransport struct {
	agents  AgentLookupStore
	clients AgentControlClientFactory
}

func NewDirectTransport(agents AgentLookupStore, clients AgentControlClientFactory) *DirectTransport {
	return &DirectTransport{
		agents:  agents,
		clients: clients,
	}
}

func (*DirectTransport) Mode() string {
	return "direct"
}

func (t *DirectTransport) DispatchAssign(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	client, err := t.clientForAgent(ctx, cmd.AgentID)
	if err != nil {
		return err
	}

	var payload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(cmd.Payload, &payload); err != nil {
		return err
	}

	return client.AssignTask(ctx, &runtimev1.AssignTaskRequest{
		TaskId:      payload.TaskID.String(),
		ExecutionId: payload.ExecutionID,
		TaskType:    payload.TaskType,
		Payload:     resolvedParamsPayload(payload.ResolvedParams),
	})
}

func (t *DirectTransport) DispatchCancel(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	client, err := t.clientForAgent(ctx, cmd.AgentID)
	if err != nil {
		return err
	}

	var payload commands.StopTaskOutboxPayload
	if err := json.Unmarshal(cmd.Payload, &payload); err != nil {
		return err
	}

	return client.StopTask(ctx, &runtimev1.StopTaskRequest{
		TaskId:      payload.TaskID.String(),
		ExecutionId: payload.ExecutionID,
		Reason:      payload.Reason,
	})
}

func (t *DirectTransport) clientForAgent(ctx context.Context, agentID string) (AgentControlClient, error) {
	if t == nil || t.agents == nil || t.clients == nil {
		return nil, fmt.Errorf("%w: direct transport dependencies are incomplete", ErrTransportNotConfigured)
	}

	agent, err := t.agents.GetByID(ctx, agentID)
	if err != nil {
		return nil, err
	}
	if agent == nil {
		return nil, fmt.Errorf("%w: agent %s not found", ErrTransportNotConfigured, agentID)
	}
	if agent.ControlBaseURL == "" {
		return nil, fmt.Errorf("%w: agent %s missing control_base_url", ErrTransportNotConfigured, agentID)
	}

	client := t.clients.New(agent.ControlBaseURL)
	if client == nil {
		return nil, fmt.Errorf("%w: agent %s has no control client", ErrTransportNotConfigured, agentID)
	}
	return client, nil
}

func resolvedParamsPayload(raw []byte) []byte {
	if len(raw) == 0 {
		return []byte(`{}`)
	}
	return append([]byte(nil), raw...)
}
