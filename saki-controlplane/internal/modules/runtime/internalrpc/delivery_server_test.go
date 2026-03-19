package internalrpc

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
)

func TestAgentDeliveryPullCommandsClaimsForSpecificAgent(t *testing.T) {
	claimToken := uuid.MustParse("7b2ec4d2-9d9c-4f27-b7df-53295d85f3dc")
	store := &fakePullCommandStore{
		claimed: []runtimerepo.AgentCommand{
			{
				CommandID:   uuid.MustParse("7d4ca218-2ef1-4b08-a7a8-eb34ae541539"),
				AgentID:     "agent-pull-1",
				TaskID:      uuid.MustParse("550e8400-e29b-41d4-a716-446655440000"),
				CommandType: "assign",
				Payload:     []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","task_type":"predict","resolved_params":{"prompt":"hello"}}`),
				ClaimToken:  &claimToken,
			},
		},
	}
	server := NewDeliveryServer(store)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentDeliveryHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentDeliveryClient(http.DefaultClient, httpServer.URL)
	resp, err := client.PullCommands(context.Background(), connect.NewRequest(&runtimev1.PullCommandsRequest{
		AgentId:       "agent-pull-1",
		MaxItems:      8,
		WaitTimeoutMs: 25000,
	}))
	if err != nil {
		t.Fatalf("pull commands: %v", err)
	}
	if len(resp.Msg.GetCommands()) != 1 {
		t.Fatalf("expected one pulled command, got %+v", resp.Msg.GetCommands())
	}
	if got := resp.Msg.GetCommands()[0]; got.GetCommandType() != "assign" || got.GetExecutionId() != "exec-1" || got.GetDeliveryToken() != claimToken.String() {
		t.Fatalf("unexpected pulled command: %+v", got)
	}
}

func TestAgentDeliveryAckCommandMarksCommandReceived(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakePullCommandStore{}
	server := NewDeliveryServer(store)
	server.now = func() time.Time { return now }

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentDeliveryHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentDeliveryClient(http.DefaultClient, httpServer.URL)
	_, err := client.AckCommand(context.Background(), connect.NewRequest(&runtimev1.AckCommandRequest{
		CommandId:     "7d4ca218-2ef1-4b08-a7a8-eb34ae541539",
		DeliveryToken: "7b2ec4d2-9d9c-4f27-b7df-53295d85f3dc",
		State:         "received",
	}))
	if err != nil {
		t.Fatalf("ack command: %v", err)
	}

	if store.ack == nil || store.finish == nil {
		t.Fatalf("expected ack and finish to be recorded, got ack=%+v finish=%+v", store.ack, store.finish)
	}
	if !store.ack.at.Equal(now) || !store.finish.at.Equal(now) {
		t.Fatalf("unexpected ack timestamps: ack=%+v finish=%+v", store.ack, store.finish)
	}
}

type fakePullCommandStore struct {
	claimed []runtimerepo.AgentCommand
	ack     *fakePullAckCall
	finish  *fakePullFinishCall
}

func (f *fakePullCommandStore) ClaimForPull(_ context.Context, _ string, _ int32, _ time.Time) ([]runtimerepo.AgentCommand, error) {
	return append([]runtimerepo.AgentCommand(nil), f.claimed...), nil
}

func (f *fakePullCommandStore) Ack(_ context.Context, commandID, claimToken uuid.UUID, ackAt time.Time) error {
	f.ack = &fakePullAckCall{commandID: commandID, claimToken: claimToken, at: ackAt}
	return nil
}

func (f *fakePullCommandStore) MarkFinished(_ context.Context, commandID, claimToken uuid.UUID, finishedAt time.Time) error {
	f.finish = &fakePullFinishCall{commandID: commandID, claimToken: claimToken, at: finishedAt}
	return nil
}

type fakePullAckCall struct {
	commandID  uuid.UUID
	claimToken uuid.UUID
	at         time.Time
}

type fakePullFinishCall struct {
	commandID  uuid.UUID
	claimToken uuid.UUID
	at         time.Time
}
