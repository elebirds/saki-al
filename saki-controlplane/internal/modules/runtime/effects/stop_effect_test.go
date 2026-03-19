package effects

import (
	"context"
	"errors"
	"testing"
	"time"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
)

func TestStopEffect_UsesAgentCommandRepoNotStaticBaseURL(t *testing.T) {
	clientA := &fakeAgentControlClient{}
	clientB := &fakeAgentControlClient{}
	effect := NewStopEffect(NewTransportRegistry(
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
		AgentID:       "agent-b",
		CommandType:   "cancel",
		TransportMode: "direct",
		Payload:       []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","agent_id":"agent-b","reason":"cancel_requested","leader_epoch":7}`),
	})
	if err != nil {
		t.Fatalf("apply stop effect: %v", err)
	}

	if clientB.stop == nil {
		t.Fatal("expected stop request to use agent-b transport")
	}
	if clientB.stop.TaskId != "550e8400-e29b-41d4-a716-446655440000" || clientB.stop.ExecutionId != "exec-1" || clientB.stop.Reason != "cancel_requested" {
		t.Fatalf("unexpected stop request: %+v", clientB.stop)
	}
	if clientA.stop != nil {
		t.Fatalf("expected command to avoid unrelated transport, got %+v", clientA.stop)
	}
}

func TestWorkerAcksAndFinishesCommandWhenEffectSucceeds(t *testing.T) {
	now := time.Unix(1700000000, 0)
	claimToken := uuid.New()
	store := &fakeAgentCommandStore{
		claimed: []repo.AgentCommand{
			{
				CommandID:     uuid.New(),
				AgentID:       "agent-1",
				CommandType:   "assign",
				TransportMode: "direct",
				Payload:       []byte(`{"task_id":"task-1"}`),
				ClaimToken:    &claimToken,
			},
		},
	}
	worker := NewWorker(store, &fakeCommandEffect{commandType: "assign"})
	worker.now = func() time.Time { return now }
	worker.claimLimit = 1
	worker.claimTTL = 30 * time.Second
	worker.retryBackoff = time.Minute

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}

	if store.ack == nil {
		t.Fatal("expected command ack")
	}
	if store.finish == nil {
		t.Fatal("expected command finish")
	}
	if store.ack.commandID != store.claimed[0].CommandID || store.finish.commandID != store.claimed[0].CommandID {
		t.Fatalf("unexpected ack/finish calls: ack=%+v finish=%+v", store.ack, store.finish)
	}
	if store.retry != nil {
		t.Fatalf("expected no retry on success, got %+v", store.retry)
	}
}

func TestWorkerMarksRetryWhenEffectFails(t *testing.T) {
	now := time.Unix(1700000000, 0)
	claimToken := uuid.New()
	store := &fakeAgentCommandStore{
		claimed: []repo.AgentCommand{
			{
				CommandID:     uuid.New(),
				AgentID:       "agent-1",
				CommandType:   "cancel",
				TransportMode: "relay",
				Payload:       []byte(`{"task_id":"task-7"}`),
				ClaimToken:    &claimToken,
			},
		},
	}
	worker := NewWorker(store, &fakeCommandEffect{commandType: "cancel", err: errors.New("transport unavailable")})
	worker.now = func() time.Time { return now }
	worker.claimLimit = 1
	worker.claimTTL = 15 * time.Second
	worker.retryBackoff = 2 * time.Minute

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}

	if store.ack != nil || store.finish != nil {
		t.Fatalf("expected failed dispatch to avoid ack/finish, got ack=%+v finish=%+v", store.ack, store.finish)
	}
	if store.retry == nil {
		t.Fatal("expected retry mark")
	}
	if store.retry.commandID != store.claimed[0].CommandID {
		t.Fatalf("unexpected retry call: %+v", store.retry)
	}
	if store.retry.lastError != "transport unavailable" {
		t.Fatalf("unexpected retry error: %+v", store.retry)
	}
}

func TestWorkerMarksRetryWhenNoEffectRegisteredForCommandType(t *testing.T) {
	now := time.Unix(1700000000, 0)
	claimToken := uuid.New()
	store := &fakeAgentCommandStore{
		claimed: []repo.AgentCommand{
			{
				CommandID:     uuid.New(),
				AgentID:       "agent-1",
				CommandType:   "legacy",
				TransportMode: "direct",
				Payload:       []byte(`{"task_id":"task-11"}`),
				ClaimToken:    &claimToken,
			},
		},
	}
	worker := NewWorker(store, &fakeCommandEffect{commandType: "assign"})
	worker.now = func() time.Time { return now }
	worker.claimLimit = 1
	worker.claimTTL = 10 * time.Second
	worker.retryBackoff = time.Minute

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}

	if store.retry == nil {
		t.Fatal("expected retry mark for unknown command type")
	}
	if store.retry.lastError != "no effect registered for command type legacy" {
		t.Fatalf("unexpected retry error: %+v", store.retry)
	}
}

type fakeAgentControlClient struct {
	assign *runtimev1.AssignTaskRequest
	stop   *runtimev1.StopTaskRequest
}

func (f *fakeAgentControlClient) AssignTask(_ context.Context, req *runtimev1.AssignTaskRequest) error {
	f.assign = req
	return nil
}

func (f *fakeAgentControlClient) StopTask(_ context.Context, req *runtimev1.StopTaskRequest) error {
	f.stop = req
	return nil
}

type fakeAgentLookupStore struct {
	agents map[string]*repo.Agent
}

func (f *fakeAgentLookupStore) GetByID(_ context.Context, agentID string) (*repo.Agent, error) {
	if f.agents == nil {
		return nil, nil
	}
	return f.agents[agentID], nil
}

type fakeCommandEffect struct {
	commandType string
	applied     []repo.AgentCommand
	err         error
}

func (f *fakeCommandEffect) CommandType() string {
	return f.commandType
}

func (f *fakeCommandEffect) Apply(_ context.Context, cmd repo.AgentCommand) error {
	f.applied = append(f.applied, cmd)
	return f.err
}

type fakeAgentCommandStore struct {
	claimed []repo.AgentCommand

	ack    *agentCommandAckCall
	finish *agentCommandFinishCall
	retry  *agentCommandRetryCall
}

func (f *fakeAgentCommandStore) ClaimForPush(_ context.Context, limit int32, claimUntil time.Time) ([]repo.AgentCommand, error) {
	if limit != 1 {
		panic("unexpected limit")
	}
	_ = claimUntil
	return append([]repo.AgentCommand(nil), f.claimed...), nil
}

func (f *fakeAgentCommandStore) Ack(_ context.Context, commandID, claimToken uuid.UUID, ackAt time.Time) error {
	f.ack = &agentCommandAckCall{
		commandID:  commandID,
		claimToken: claimToken,
		at:         ackAt,
	}
	return nil
}

func (f *fakeAgentCommandStore) MarkFinished(_ context.Context, commandID, claimToken uuid.UUID, finishedAt time.Time) error {
	f.finish = &agentCommandFinishCall{
		commandID:  commandID,
		claimToken: claimToken,
		at:         finishedAt,
	}
	return nil
}

func (f *fakeAgentCommandStore) MarkRetry(_ context.Context, commandID, claimToken uuid.UUID, nextAvailableAt time.Time, lastError string) error {
	f.retry = &agentCommandRetryCall{
		commandID:       commandID,
		claimToken:      claimToken,
		nextAvailableAt: nextAvailableAt,
		lastError:       lastError,
	}
	return nil
}

type agentCommandAckCall struct {
	commandID  uuid.UUID
	claimToken uuid.UUID
	at         time.Time
}

type agentCommandFinishCall struct {
	commandID  uuid.UUID
	claimToken uuid.UUID
	at         time.Time
}

type agentCommandRetryCall struct {
	commandID       uuid.UUID
	claimToken      uuid.UUID
	nextAvailableAt time.Time
	lastError       string
}
