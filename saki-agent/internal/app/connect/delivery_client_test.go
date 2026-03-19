package connect

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
)

func TestDeliveryClientPullCommandsUsesAgentIdentity(t *testing.T) {
	server := &recordingAgentDeliveryServer{
		pullResponse: &runtimev1.PullCommandsResponse{
			Commands: []*runtimev1.PulledCommand{
				{
					CommandId:     "cmd-1",
					CommandType:   "assign",
					TaskId:        "task-1",
					ExecutionId:   "exec-1",
					Payload:       []byte(`{"task_type":"predict"}`),
					DeliveryToken: "token-1",
				},
			},
		},
	}
	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentDeliveryHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := NewDeliveryClient(http.DefaultClient, httpServer.URL, "agent-pull-1")
	commands, err := client.PullCommands(context.Background(), 8, 25_000)
	if err != nil {
		t.Fatalf("pull commands: %v", err)
	}

	if server.pull == nil || server.pull.GetAgentId() != "agent-pull-1" || server.pull.GetMaxItems() != 8 {
		t.Fatalf("unexpected pull request: %+v", server.pull)
	}
	if len(commands) != 1 || commands[0].GetCommandId() != "cmd-1" {
		t.Fatalf("unexpected pulled commands: %+v", commands)
	}
}

func TestDeliveryClientAckReceivedUsesDeliveryToken(t *testing.T) {
	server := &recordingAgentDeliveryServer{
		ackResponse: &runtimev1.AckCommandResponse{Accepted: true},
	}
	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentDeliveryHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := NewDeliveryClient(http.DefaultClient, httpServer.URL, "agent-pull-1")
	if err := client.AckReceived(context.Background(), "cmd-1", "token-1"); err != nil {
		t.Fatalf("ack received: %v", err)
	}

	if server.ack == nil || server.ack.GetCommandId() != "cmd-1" || server.ack.GetDeliveryToken() != "token-1" || server.ack.GetState() != "received" {
		t.Fatalf("unexpected ack request: %+v", server.ack)
	}
}

type recordingAgentDeliveryServer struct {
	runtimev1connect.UnimplementedAgentDeliveryHandler

	pull         *runtimev1.PullCommandsRequest
	pullResponse *runtimev1.PullCommandsResponse
	ack          *runtimev1.AckCommandRequest
	ackResponse  *runtimev1.AckCommandResponse
}

func (s *recordingAgentDeliveryServer) PullCommands(_ context.Context, req *connect.Request[runtimev1.PullCommandsRequest]) (*connect.Response[runtimev1.PullCommandsResponse], error) {
	s.pull = req.Msg
	return connect.NewResponse(s.pullResponse), nil
}

func (s *recordingAgentDeliveryServer) AckCommand(_ context.Context, req *connect.Request[runtimev1.AckCommandRequest]) (*connect.Response[runtimev1.AckCommandResponse], error) {
	s.ack = req.Msg
	return connect.NewResponse(s.ackResponse), nil
}
