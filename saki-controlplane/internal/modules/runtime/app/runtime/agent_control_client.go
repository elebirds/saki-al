package runtime

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
)

var errAgentControlRejected = errors.New("agent control request was not accepted")

type agentControlTransport interface {
	AssignTask(ctx context.Context, req *runtimev1.AssignTaskRequest) error
	StopTask(ctx context.Context, req *runtimev1.StopTaskRequest) error
}

type connectAgentControlClient struct {
	client runtimev1connect.AgentControlClient
}

func newAgentControlTransport(httpClient *http.Client, baseURL string, logger *slog.Logger) agentControlTransport {
	if strings.TrimSpace(baseURL) == "" {
		return &placeholderAgentControlClient{logger: loggerOrDefault(logger)}
	}
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &connectAgentControlClient{
		client: runtimev1connect.NewAgentControlClient(httpClient, baseURL),
	}
}

func (c *connectAgentControlClient) AssignTask(ctx context.Context, req *runtimev1.AssignTaskRequest) error {
	resp, err := c.client.AssignTask(ctx, connect.NewRequest(req))
	if err != nil {
		return err
	}
	if !resp.Msg.GetAccepted() {
		return errAgentControlRejected
	}
	return nil
}

func (c *connectAgentControlClient) StopTask(ctx context.Context, req *runtimev1.StopTaskRequest) error {
	resp, err := c.client.StopTask(ctx, connect.NewRequest(req))
	if err != nil {
		return err
	}
	if !resp.Msg.GetAccepted() {
		return errAgentControlRejected
	}
	return nil
}
