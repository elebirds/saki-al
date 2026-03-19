package effects

import (
	"context"
	"testing"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
)

func TestDispatchEffect_UsesDirectTransportPerAgent(t *testing.T) {
	clientA := &fakeAgentControlClient{}
	clientB := &fakeAgentControlClient{}
	effect := NewDispatchEffect(NewTransportRegistry(
		NewDirectTransport(
			&fakeAgentLookupStore{
				agents: map[string]*repo.Agent{
					"agent-a": {
						ID:             "agent-a",
						TransportMode:  "direct",
						ControlBaseURL: "http://agent-a.control",
					},
					"agent-b": {
						ID:             "agent-b",
						TransportMode:  "direct",
						ControlBaseURL: "http://agent-b.control",
					},
				},
			},
			AgentControlClientFactoryFunc(func(baseURL string) AgentControlClient {
				switch baseURL {
				case "http://agent-a.control":
					return clientA
				case "http://agent-b.control":
					return clientB
				default:
					t.Fatalf("unexpected base url: %s", baseURL)
					return nil
				}
			}),
		),
		NewPullTransport(),
	))

	err := effect.Apply(context.Background(), repo.AgentCommand{
		CommandID:     uuid.New(),
		AgentID:       "agent-a",
		CommandType:   "assign",
		TransportMode: "direct",
		Payload:       []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","agent_id":"agent-a","task_kind":"PREDICTION","task_type":"predict","attempt":1,"max_attempts":3,"resolved_params":{"prompt":"hello"},"depends_on_task_ids":[],"leader_epoch":7}`),
	})
	if err != nil {
		t.Fatalf("apply dispatch effect: %v", err)
	}

	if clientA.assign == nil || clientA.assign.TaskId != "550e8400-e29b-41d4-a716-446655440000" {
		t.Fatalf("unexpected direct assign request: %+v", clientA.assign)
	}
	if clientA.assign.ExecutionId != "exec-1" || clientA.assign.TaskType != "predict" {
		t.Fatalf("unexpected direct assign request: %+v", clientA.assign)
	}
	if string(clientA.assign.Payload) != `{"prompt":"hello"}` {
		t.Fatalf("unexpected assign payload: %s", string(clientA.assign.Payload))
	}
	if clientB.assign != nil {
		t.Fatalf("expected command to use agent-a transport only, got %+v", clientB.assign)
	}
}

func TestDispatchEffect_PullModeLeavesCommandForAgentClaim(t *testing.T) {
	client := &fakeAgentControlClient{}
	effect := NewDispatchEffect(NewTransportRegistry(
		NewDirectTransport(
			&fakeAgentLookupStore{
				agents: map[string]*repo.Agent{
					"agent-pull": {
						ID:             "agent-pull",
						TransportMode:  "pull",
						ControlBaseURL: "http://agent-pull.control",
					},
				},
			},
			AgentControlClientFactoryFunc(func(string) AgentControlClient {
				return client
			}),
		),
		NewPullTransport(),
	))

	err := effect.Apply(context.Background(), repo.AgentCommand{
		CommandID:     uuid.New(),
		AgentID:       "agent-pull",
		CommandType:   "assign",
		TransportMode: "pull",
		Payload:       []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-pull-1","agent_id":"agent-pull","task_kind":"PREDICTION","task_type":"predict","attempt":1,"max_attempts":3,"resolved_params":{"prompt":"hello"},"depends_on_task_ids":[],"leader_epoch":7}`),
	})
	if err != nil {
		t.Fatalf("apply dispatch effect: %v", err)
	}

	if client.assign != nil {
		t.Fatalf("expected pull mode command to stay claimable by agent, got %+v", client.assign)
	}
}
