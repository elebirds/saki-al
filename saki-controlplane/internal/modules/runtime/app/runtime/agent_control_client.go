package runtime

import (
	"context"
	"errors"
	"net/http"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
)

var errAgentControlRejected = errors.New("agent control request was not accepted")

type connectAgentControlClientFactory struct {
	httpClient *http.Client
}

func newAgentControlClientFactory(httpClient *http.Client) runtimeeffects.AgentControlClientFactory {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return connectAgentControlClientFactory{httpClient: httpClient}
}

func (f connectAgentControlClientFactory) New(baseURL string) runtimeeffects.AgentControlClient {
	return &connectAgentControlClient{
		client: runtimev1connect.NewAgentControlClient(f.httpClient, baseURL),
	}
}

type connectAgentControlClient struct {
	client runtimev1connect.AgentControlClient
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
