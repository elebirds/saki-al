package runtimegrpc

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/rs/zerolog"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/proto"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

type fakeRuntimeDomainServer struct {
	runtimedomainv1.UnimplementedRuntimeDomainServer
	onCreateDownloadTicket func(ctx context.Context, req *runtimedomainv1.DownloadTicketRequest) (*runtimedomainv1.DownloadTicketResponse, error)
}

func (f *fakeRuntimeDomainServer) CreateDownloadTicket(
	ctx context.Context,
	req *runtimedomainv1.DownloadTicketRequest,
) (*runtimedomainv1.DownloadTicketResponse, error) {
	return f.onCreateDownloadTicket(ctx, req)
}

func startRuntimeDomainTestClient(
	t *testing.T,
	server runtimedomainv1.RuntimeDomainServer,
) *runtime_domain_client.Client {
	t.Helper()

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen failed: %v", err)
	}

	grpcServer := grpc.NewServer()
	runtimedomainv1.RegisterRuntimeDomainServer(grpcServer, server)
	go func() {
		_ = grpcServer.Serve(listener)
	}()

	client := runtime_domain_client.New(listener.Addr().String(), "", 5)
	connectCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := client.Connect(connectCtx); err != nil {
		t.Fatalf("connect runtime domain client failed: %v", err)
	}

	t.Cleanup(func() {
		_ = client.Close()
		grpcServer.Stop()
		_ = listener.Close()
	})
	return client
}

func TestHandleIncomingDownloadTicketRequestProxy(t *testing.T) {
	tests := []struct {
		name                string
		sourceTaskID        string
		modelID             string
		expectedUpstreamID  string
		expectedUpstreamMID string
	}{
		{
			name:               "source_task",
			sourceTaskID:       "source-task-1",
			expectedUpstreamID: "source-task-1",
		},
		{
			name:                "model_id",
			modelID:             "model-1",
			expectedUpstreamMID: "model-1",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			client := startRuntimeDomainTestClient(t, &fakeRuntimeDomainServer{
				onCreateDownloadTicket: func(_ context.Context, req *runtimedomainv1.DownloadTicketRequest) (*runtimedomainv1.DownloadTicketResponse, error) {
					if req.GetTaskId() != tc.expectedUpstreamID {
						t.Fatalf("upstream task_id mismatch: got=%q want=%q", req.GetTaskId(), tc.expectedUpstreamID)
					}
					if req.GetModelId() != tc.expectedUpstreamMID {
						t.Fatalf("upstream model_id mismatch: got=%q want=%q", req.GetModelId(), tc.expectedUpstreamMID)
					}
					if req.GetArtifactName() != "best.pt" {
						t.Fatalf("upstream artifact name mismatch: got=%q", req.GetArtifactName())
					}
					return &runtimedomainv1.DownloadTicketResponse{
						RequestId:    "resp-1",
						ReplyTo:      req.GetRequestId(),
						TaskId:       req.GetTaskId(),
						ModelId:      req.GetModelId(),
						ArtifactName: req.GetArtifactName(),
						DownloadUrl:  "https://example.com/runtime/best.pt",
						StorageUri:   "s3://bucket/runtime/best.pt",
						Headers: map[string]string{
							"Authorization": "Bearer test-token",
						},
					}, nil
				},
			})

			server := &Server{
				domainClient: client,
				logger:       zerolog.Nop(),
			}
			consumerTaskID := "consumer-task-1"
			message := &runtimecontrolv1.RuntimeMessage{
				Payload: &runtimecontrolv1.RuntimeMessage_DownloadTicketRequest{
					DownloadTicketRequest: &runtimecontrolv1.DownloadTicketRequest{
						RequestId:    "req-1",
						TaskId:       consumerTaskID,
						ExecutionId:  "execution-1",
						SourceTaskId: tc.sourceTaskID,
						ModelId:      tc.modelID,
						ArtifactName: "best.pt",
					},
				},
			}

			responses, nextExecutorID, err := server.handleIncoming(message, "")
			if err != nil {
				t.Fatalf("handleIncoming failed: %v", err)
			}
			if nextExecutorID != "" {
				t.Fatalf("unexpected next executor id: %q", nextExecutorID)
			}
			if len(responses) != 1 {
				t.Fatalf("response count mismatch: got=%d", len(responses))
			}
			response := responses[0].GetDownloadTicketResponse()
			if response == nil {
				t.Fatalf("expected download ticket response payload, got=%T", responses[0].GetPayload())
			}
			if response.GetTaskId() != consumerTaskID {
				t.Fatalf("consumer task_id mismatch: got=%q want=%q", response.GetTaskId(), consumerTaskID)
			}
			if response.GetSourceTaskId() != tc.sourceTaskID {
				t.Fatalf("source_task_id mismatch: got=%q want=%q", response.GetSourceTaskId(), tc.sourceTaskID)
			}
			if response.GetModelId() != tc.modelID {
				t.Fatalf("model_id mismatch: got=%q want=%q", response.GetModelId(), tc.modelID)
			}
			if response.GetDownloadUrl() != "https://example.com/runtime/best.pt" {
				t.Fatalf("download_url mismatch: got=%q", response.GetDownloadUrl())
			}
			if response.GetStorageUri() != "s3://bucket/runtime/best.pt" {
				t.Fatalf("storage_uri mismatch: got=%q", response.GetStorageUri())
			}
			if response.GetHeaders()["Authorization"] != "Bearer test-token" {
				t.Fatalf("headers mismatch: got=%v", response.GetHeaders())
			}
		})
	}
}

func TestHandleIncomingDownloadTicketRequestReturnsNotImplementedWhenDomainDisabled(t *testing.T) {
	server := &Server{logger: zerolog.Nop()}
	message := &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_DownloadTicketRequest{
			DownloadTicketRequest: &runtimecontrolv1.DownloadTicketRequest{
				RequestId:    "req-disabled-1",
				TaskId:       "consumer-task-1",
				ExecutionId:  "execution-1",
				SourceTaskId: "source-task-1",
				ArtifactName: "best.pt",
			},
		},
	}

	responses, nextExecutorID, err := server.handleIncoming(message, "")
	if err != nil {
		t.Fatalf("handleIncoming failed: %v", err)
	}
	if nextExecutorID != "" {
		t.Fatalf("unexpected next executor id: %q", nextExecutorID)
	}
	if len(responses) != 1 {
		t.Fatalf("response count mismatch: got=%d", len(responses))
	}
	errPayload := responses[0].GetError()
	if errPayload == nil {
		t.Fatalf("expected error payload, got=%T", responses[0].GetPayload())
	}
	if errPayload.GetCode() != "not_implemented" {
		t.Fatalf("error code mismatch: got=%q", errPayload.GetCode())
	}
	if errPayload.GetMessage() != "runtime_domain CreateDownloadTicket 未配置" {
		t.Fatalf("error message mismatch: got=%q", errPayload.GetMessage())
	}
	if errPayload.GetTaskId() != "consumer-task-1" {
		t.Fatalf("error task_id mismatch: got=%q", errPayload.GetTaskId())
	}
}

func TestTaskResultChunkAssemblerBuildsOriginalTaskResult(t *testing.T) {
	largeSuffix := strings.Repeat("x", 1024)
	result := &runtimecontrolv1.TaskResult{
		RequestId:   "req-result-1",
		TaskId:      "task-result-1",
		ExecutionId: "execution-result-1",
		Status:      runtimecontrolv1.RuntimeTaskStatus_SUCCEEDED,
	}
	for index := 0; index < 4000; index++ {
		result.Candidates = append(result.Candidates, &runtimecontrolv1.QueryCandidate{
			SampleId: "sample-" + time.Unix(int64(index), 0).UTC().Format("150405") + "-" + largeSuffix,
			Score:    0.8,
		})
	}

	chunks, err := buildTaskResultChunkMessages(result, 256*1024)
	if err != nil {
		t.Fatalf("buildTaskResultChunkMessages failed: %v", err)
	}
	if len(chunks) <= 1 {
		t.Fatalf("expected chunked messages, got=%d", len(chunks))
	}

	assembler := newTaskResultChunkAssembler()
	var rebuilt *runtimecontrolv1.TaskResult
	for _, message := range chunks {
		chunk := message.GetTaskResultChunk()
		if chunk == nil {
			t.Fatalf("expected task_result_chunk payload")
		}
		item, done, addErr := assembler.add(chunk)
		if addErr != nil {
			t.Fatalf("assembler.add failed: %v", addErr)
		}
		if done {
			rebuilt = item
		}
	}
	if rebuilt == nil {
		t.Fatalf("expected rebuilt task result")
	}

	originalBytes, err := proto.Marshal(result)
	if err != nil {
		t.Fatalf("marshal original failed: %v", err)
	}
	rebuiltBytes, err := proto.Marshal(rebuilt)
	if err != nil {
		t.Fatalf("marshal rebuilt failed: %v", err)
	}
	if !proto.Equal(result, rebuilt) || string(originalBytes) != string(rebuiltBytes) {
		t.Fatalf("rebuilt task result bytes mismatch")
	}
}

func TestTaskResultChunkAssemblerRejectsChecksumMismatch(t *testing.T) {
	largeSuffix := strings.Repeat("y", 1024)
	result := &runtimecontrolv1.TaskResult{
		RequestId: "req-result-bad",
		TaskId:    "task-result-bad",
		Status:    runtimecontrolv1.RuntimeTaskStatus_SUCCEEDED,
	}
	for index := 0; index < 2000; index++ {
		result.Candidates = append(result.Candidates, &runtimecontrolv1.QueryCandidate{
			SampleId: "sample-" + largeSuffix,
			Score:    float64(index),
		})
	}

	chunks, err := buildTaskResultChunkMessages(result, 128*1024)
	if err != nil {
		t.Fatalf("buildTaskResultChunkMessages failed: %v", err)
	}
	if len(chunks) <= 1 {
		t.Fatalf("expected chunked messages, got=%d", len(chunks))
	}

	chunk := chunks[0].GetTaskResultChunk()
	chunk.PayloadChunk = append([]byte{}, chunk.PayloadChunk...)
	chunk.PayloadChunk[0] ^= 0xFF

	assembler := newTaskResultChunkAssembler()
	if _, _, err := assembler.add(chunk); err == nil {
		t.Fatalf("expected checksum mismatch error")
	}
}
