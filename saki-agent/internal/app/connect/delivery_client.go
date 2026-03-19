package connect

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net"
	"net/http"
	"time"

	connectrpc "connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
	"golang.org/x/net/http2"
)

var errDeliveryRequestRejected = errors.New("runtime delivery request was not accepted")
var errRelayRequestRejected = errors.New("runtime relay request was not accepted")

const (
	relayFrameAgentHello   = "agent_hello"
	relayFrameAgentWelcome = "agent_welcome"
	relayFrameCommand      = "command"
	relayFrameCommandReply = "command_result"
)

type deliveryAPIClient interface {
	PullCommands(context.Context, *connectrpc.Request[runtimev1.PullCommandsRequest]) (*connectrpc.Response[runtimev1.PullCommandsResponse], error)
	AckCommand(context.Context, *connectrpc.Request[runtimev1.AckCommandRequest]) (*connectrpc.Response[runtimev1.AckCommandResponse], error)
}

type relayAPIClient interface {
	Open(context.Context) *connectrpc.BidiStreamForClient[runtimev1.RelayFrame, runtimev1.RelayFrame]
}

type DeliveryClient struct {
	agentID string
	mode    string
	client  deliveryAPIClient
	relay   relayAPIClient
	now     func() time.Time
}

func NewDeliveryClient(httpClient *http.Client, baseURL string, agentID string) *DeliveryClient {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &DeliveryClient{
		agentID: agentID,
		mode:    "pull",
		client:  runtimev1connect.NewAgentDeliveryClient(httpClient, baseURL),
		now:     time.Now,
	}
}

func NewRelayDeliveryClient(httpClient *http.Client, baseURL string, agentID string) *DeliveryClient {
	if httpClient == nil {
		httpClient = newH2CClient()
	}
	return &DeliveryClient{
		agentID: agentID,
		mode:    "relay",
		relay:   runtimev1connect.NewAgentRelayClient(httpClient, baseURL),
		now:     time.Now,
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

func (c *DeliveryClient) DeliveryMode() string {
	if c == nil || c.mode == "" {
		return "pull"
	}
	return c.mode
}

func (c *DeliveryClient) OpenRelaySession(ctx context.Context, handler func(context.Context, *runtimev1.PulledCommand) error) error {
	if c == nil || c.mode != "relay" || c.relay == nil {
		return errRelayRequestRejected
	}

	stream := c.relay.Open(ctx)
	if err := stream.Send(&runtimev1.RelayFrame{
		FrameKind:    relayFrameAgentHello,
		AgentId:      c.agentID,
		SentAtUnixMs: c.now().UnixMilli(),
	}); err != nil {
		return err
	}

	welcome, err := stream.Receive()
	if err != nil {
		return err
	}
	if welcome.GetFrameKind() != relayFrameAgentWelcome || !welcome.GetAccepted() {
		return errRelayRequestRejected
	}

	for {
		frame, err := stream.Receive()
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(ctx.Err(), context.Canceled) {
				return nil
			}
			return err
		}
		if frame == nil || frame.GetFrameKind() != relayFrameCommand {
			continue
		}

		command := &runtimev1.PulledCommand{
			CommandId:   frame.GetCommandId(),
			CommandType: frame.GetCommandType(),
			TaskId:      frame.GetTaskId(),
			ExecutionId: frame.GetExecutionId(),
			Payload:     append([]byte(nil), frame.GetPayload()...),
		}

		accepted := true
		errMessage := ""
		if err := handler(ctx, command); err != nil {
			accepted = false
			errMessage = err.Error()
		}

		if err := stream.Send(&runtimev1.RelayFrame{
			FrameKind:    relayFrameCommandReply,
			AgentId:      c.agentID,
			SessionId:    welcome.GetSessionId(),
			CommandId:    frame.GetCommandId(),
			CommandType:  frame.GetCommandType(),
			TaskId:       frame.GetTaskId(),
			ExecutionId:  frame.GetExecutionId(),
			Accepted:     accepted,
			ErrorMessage: errMessage,
			SentAtUnixMs: c.now().UnixMilli(),
		}); err != nil {
			return err
		}
	}
}

func newH2CClient() *http.Client {
	return &http.Client{
		Transport: &http2.Transport{
			AllowHTTP: true,
			DialTLSContext: func(ctx context.Context, network, addr string, _ *tls.Config) (net.Conn, error) {
				var d net.Dialer
				return d.DialContext(ctx, network, addr)
			},
		},
	}
}
