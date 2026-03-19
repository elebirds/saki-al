package connect

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	connectrpc "connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
)

var errRuntimeRequestRejected = errors.New("runtime ingress request was not accepted")

type ingressClient interface {
	Register(context.Context, *connectrpc.Request[runtimev1.RegisterRequest]) (*connectrpc.Response[runtimev1.RegisterResponse], error)
	Heartbeat(context.Context, *connectrpc.Request[runtimev1.HeartbeatRequest]) (*connectrpc.Response[runtimev1.HeartbeatResponse], error)
	PushTaskEvent(context.Context, *connectrpc.Request[runtimev1.PushTaskEventRequest]) (*connectrpc.Response[runtimev1.PushTaskEventResponse], error)
}

type RuntimeClient struct {
	agentID        string
	agentVersion   string
	transportMode  string
	controlBaseURL string
	maxConcurrency int32
	client         ingressClient
	logger         *slog.Logger
	now            func() time.Time
}

func NewRuntimeClient(
	httpClient *http.Client,
	baseURL string,
	agentID string,
	agentVersion string,
	transportMode string,
	controlBaseURL string,
	maxConcurrency int32,
	logger *slog.Logger,
) *RuntimeClient {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	if logger == nil {
		logger = slog.Default()
	}

	return &RuntimeClient{
		agentID:        agentID,
		agentVersion:   agentVersion,
		transportMode:  normalizeTransportMode(transportMode),
		controlBaseURL: controlBaseURL,
		maxConcurrency: normalizeMaxConcurrency(maxConcurrency),
		client:         runtimev1connect.NewAgentIngressClient(httpClient, baseURL),
		logger:         logger,
		now:            time.Now,
	}
}

func (c *RuntimeClient) Register(ctx context.Context, capabilities []string) error {
	resp, err := c.client.Register(ctx, connectrpc.NewRequest(&runtimev1.RegisterRequest{
		AgentId:        c.agentID,
		Version:        c.agentVersion,
		Capabilities:   append([]string(nil), capabilities...),
		TransportMode:  c.transportMode,
		ControlBaseUrl: c.controlBaseURL,
		MaxConcurrency: c.maxConcurrency,
	}))
	if err != nil {
		return err
	}
	if !resp.Msg.GetAccepted() {
		return errRuntimeRequestRejected
	}
	return nil
}

func (c *RuntimeClient) Heartbeat(ctx context.Context, runningTaskIDs []string) error {
	resp, err := c.client.Heartbeat(ctx, connectrpc.NewRequest(&runtimev1.HeartbeatRequest{
		AgentId:        c.agentID,
		AgentVersion:   c.agentVersion,
		RunningTaskIds: append([]string(nil), runningTaskIDs...),
		MaxConcurrency: c.maxConcurrency,
		SentAtUnixMs:   c.now().UnixMilli(),
	}))
	if err != nil {
		return err
	}
	if !resp.Msg.GetAccepted() {
		return errRuntimeRequestRejected
	}
	return nil
}

func normalizeTransportMode(mode string) string {
	if mode == "" {
		return "pull"
	}
	return mode
}

func normalizeMaxConcurrency(maxConcurrency int32) int32 {
	if maxConcurrency <= 0 {
		return 1
	}
	return maxConcurrency
}

func (c *RuntimeClient) PushTaskEvent(ctx context.Context, envelope *runtimev1.TaskEventEnvelope) error {
	resp, err := c.client.PushTaskEvent(ctx, connectrpc.NewRequest(&runtimev1.PushTaskEventRequest{
		Event: envelope,
	}))
	if err != nil {
		return err
	}
	if !resp.Msg.GetAccepted() {
		return errRuntimeRequestRejected
	}
	return nil
}
