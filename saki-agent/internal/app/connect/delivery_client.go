package connect

import (
	"context"
	"errors"
	"net/http"
	"time"

	connectrpc "connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
)

var errDeliveryRequestRejected = errors.New("runtime delivery request was not accepted")

type deliveryAPIClient interface {
	PullCommands(context.Context, *connectrpc.Request[runtimev1.PullCommandsRequest]) (*connectrpc.Response[runtimev1.PullCommandsResponse], error)
	AckCommand(context.Context, *connectrpc.Request[runtimev1.AckCommandRequest]) (*connectrpc.Response[runtimev1.AckCommandResponse], error)
}

type DeliveryClient struct {
	agentID string
	client  deliveryAPIClient
}

func NewDeliveryClient(httpClient *http.Client, baseURL string, agentID string) *DeliveryClient {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &DeliveryClient{
		agentID: agentID,
		client:  runtimev1connect.NewAgentDeliveryClient(httpClient, baseURL),
	}
}

func (c *DeliveryClient) PullCommands(ctx context.Context, maxItems int32, waitTimeout time.Duration) ([]*runtimev1.PulledCommand, error) {
	resp, err := c.client.PullCommands(ctx, connectrpc.NewRequest(&runtimev1.PullCommandsRequest{
		AgentId:       c.agentID,
		MaxItems:      maxItems,
		WaitTimeoutMs: waitTimeout.Milliseconds(),
	}))
	if err != nil {
		return nil, err
	}
	return append([]*runtimev1.PulledCommand(nil), resp.Msg.GetCommands()...), nil
}

func (c *DeliveryClient) AckReceived(ctx context.Context, commandID string, deliveryToken string) error {
	resp, err := c.client.AckCommand(ctx, connectrpc.NewRequest(&runtimev1.AckCommandRequest{
		CommandId:     commandID,
		DeliveryToken: deliveryToken,
		State:         "received",
	}))
	if err != nil {
		return err
	}
	if !resp.Msg.GetAccepted() {
		return errDeliveryRequestRejected
	}
	return nil
}
