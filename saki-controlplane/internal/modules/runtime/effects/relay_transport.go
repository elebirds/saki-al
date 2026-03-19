package effects

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net"
	"net/http"

	"connectrpc.com/connect"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"golang.org/x/net/http2"
)

const (
	relayFrameDispatch      = "dispatch_command"
	relayFrameDispatchReply = "dispatch_result"
)

type AgentSessionLookupStore interface {
	GetByAgentID(ctx context.Context, agentID string) (*runtimerepo.AgentSession, error)
}

type RelayDispatchClient interface {
	Dispatch(ctx context.Context, frame *runtimev1.RelayFrame) (*runtimev1.RelayFrame, error)
}

type RelayDispatchClientFactory interface {
	New(baseURL string) RelayDispatchClient
}

type RelayDispatchClientFactoryFunc func(baseURL string) RelayDispatchClient

func (f RelayDispatchClientFactoryFunc) New(baseURL string) RelayDispatchClient {
	return f(baseURL)
}

type RelayTransport struct {
	sessions           AgentSessionLookupStore
	clients            RelayDispatchClientFactory
	defaultRelayBaseURL string
}

func NewRelayTransport(sessions AgentSessionLookupStore, clients RelayDispatchClientFactory, defaultRelayBaseURL string) *RelayTransport {
	return &RelayTransport{
		sessions:            sessions,
		clients:             clients,
		defaultRelayBaseURL: defaultRelayBaseURL,
	}
}

func (*RelayTransport) Mode() string {
	return "relay"
}

func (t *RelayTransport) DispatchAssign(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	return t.dispatch(ctx, cmd)
}

func (t *RelayTransport) DispatchCancel(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	return t.dispatch(ctx, cmd)
}

func (t *RelayTransport) dispatch(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	if t == nil || t.sessions == nil || t.clients == nil {
		return fmt.Errorf("%w: relay transport dependencies are incomplete", ErrTransportNotConfigured)
	}

	session, err := t.sessions.GetByAgentID(ctx, cmd.AgentID)
	if err != nil {
		return err
	}
	if session == nil {
		return fmt.Errorf("%w: relay session for agent %s not found", ErrTransportNotConfigured, cmd.AgentID)
	}

	baseURL := session.RelayID
	if baseURL == "" {
		baseURL = t.defaultRelayBaseURL
	}
	if baseURL == "" {
		return fmt.Errorf("%w: relay endpoint for agent %s not configured", ErrTransportNotConfigured, cmd.AgentID)
	}

	executionID, err := relayExecutionIDFromPayload(cmd.CommandType, cmd.Payload)
	if err != nil {
		return err
	}

	// 关键设计：relay transport 只负责把 agent_command 投到在线 relay session，并等待 agent 的 handoff 回执；
	// 它自己不修改任务状态，真正的 ack/finish 仍由 delivery worker 在收到 Accepted 后统一推进。
	result, err := t.clients.New(baseURL).Dispatch(ctx, &runtimev1.RelayFrame{
		FrameKind:   relayFrameDispatch,
		AgentId:     cmd.AgentID,
		CommandId:   cmd.CommandID.String(),
		CommandType: cmd.CommandType,
		TaskId:      cmd.TaskID.String(),
		ExecutionId: executionID,
		Payload:     append([]byte(nil), cmd.Payload...),
	})
	if err != nil {
		return err
	}
	if result == nil {
		return fmt.Errorf("%w: relay dispatch result is nil", ErrTransportNotConfigured)
	}
	if !result.GetAccepted() {
		return fmt.Errorf("%w: %s", ErrTransportNotConfigured, result.GetErrorMessage())
	}
	return nil
}

type connectRelayDispatchClient struct {
	client runtimev1connect.AgentRelayClient
}

func NewConnectRelayDispatchClient(httpClient *http.Client, baseURL string) RelayDispatchClient {
	if httpClient == nil {
		httpClient = newH2CClient()
	}
	return &connectRelayDispatchClient{
		client: runtimev1connect.NewAgentRelayClient(httpClient, baseURL),
	}
}

func NewConnectRelayDispatchClientFactory(httpClient *http.Client) RelayDispatchClientFactory {
	return RelayDispatchClientFactoryFunc(func(baseURL string) RelayDispatchClient {
		return NewConnectRelayDispatchClient(httpClient, baseURL)
	})
}

func (c *connectRelayDispatchClient) Dispatch(ctx context.Context, frame *runtimev1.RelayFrame) (*runtimev1.RelayFrame, error) {
	stream := c.client.Open(ctx)
	if err := stream.Send(frame); err != nil {
		return nil, err
	}
	if err := stream.CloseRequest(); err != nil {
		return nil, err
	}

	result, err := stream.Receive()
	if err != nil {
		return nil, err
	}
	if result.GetFrameKind() != relayFrameDispatchReply {
		return nil, connect.NewError(connect.CodeInternal, fmt.Errorf("unexpected relay reply kind: %s", result.GetFrameKind()))
	}
	return result, nil
}

func relayExecutionIDFromPayload(commandType string, payload []byte) (string, error) {
	var envelope struct {
		ExecutionID string `json:"execution_id"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return "", fmt.Errorf("decode %s relay payload: %w", commandType, err)
	}
	if envelope.ExecutionID == "" {
		return "", fmt.Errorf("%s relay payload missing execution_id", commandType)
	}
	return envelope.ExecutionID, nil
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
