package runtime

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
)

func TestAgentControlClientFactoryCreatesPerBaseURLClient(t *testing.T) {
	server := &recordingAgentControlServer{}
	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentControlHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	factory := newAgentControlClientFactory(http.DefaultClient)
	client := factory.New(httpServer.URL)

	if err := client.AssignTask(context.Background(), &runtimev1.AssignTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		TaskType:    "predict",
		Payload:     []byte(`{"hello":"world"}`),
	}); err != nil {
		t.Fatalf("assign task: %v", err)
	}

	if err := client.StopTask(context.Background(), &runtimev1.StopTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		Reason:      "cancel_requested",
	}); err != nil {
		t.Fatalf("stop task: %v", err)
	}

	if server.assignTask == nil {
		t.Fatal("expected assign task rpc to reach agent control server")
	}
	if server.stopTask == nil {
		t.Fatal("expected stop task rpc to reach agent control server")
	}
}

type recordingAgentControlServer struct {
	runtimev1connect.UnimplementedAgentControlHandler

	assignTask *runtimev1.AssignTaskRequest
	stopTask   *runtimev1.StopTaskRequest
}

func (s *recordingAgentControlServer) AssignTask(_ context.Context, req *connect.Request[runtimev1.AssignTaskRequest]) (*connect.Response[runtimev1.AssignTaskResponse], error) {
	s.assignTask = req.Msg
	return connect.NewResponse(&runtimev1.AssignTaskResponse{Accepted: true}), nil
}

func (s *recordingAgentControlServer) StopTask(_ context.Context, req *connect.Request[runtimev1.StopTaskRequest]) (*connect.Response[runtimev1.StopTaskResponse], error) {
	s.stopTask = req.Msg
	return connect.NewResponse(&runtimev1.StopTaskResponse{Accepted: true}), nil
}
