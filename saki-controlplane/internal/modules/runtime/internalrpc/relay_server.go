package internalrpc

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sync"
	"time"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

const (
	relayFrameAgentHello    = "agent_hello"
	relayFrameAgentWelcome  = "agent_welcome"
	relayFrameDispatch      = "dispatch_command"
	relayFrameDispatchReply = "dispatch_result"
	relayFrameCommand       = "command"
	relayFrameCommandResult = "command_result"
	relayFramePing          = "ping"

	defaultRelayDispatchTimeout = 30 * time.Second
	defaultRelayQueueSize       = 8
)

type relaySessionStore interface {
	Upsert(ctx context.Context, params runtimerepo.UpsertAgentSessionParams) (*runtimerepo.AgentSession, error)
	Delete(ctx context.Context, sessionID string) error
	Touch(ctx context.Context, sessionID string, seenAt time.Time) error
}

type RelayServer struct {
	runtimev1connect.UnimplementedAgentRelayHandler

	relayID         string
	sessions        relaySessionStore
	hub             *relaySessionHub
	now             func() time.Time
	dispatchTimeout time.Duration
}

func NewRelayServer(relayID string, sessions relaySessionStore) *RelayServer {
	return &RelayServer{
		relayID:         relayID,
		sessions:        sessions,
		hub:             newRelaySessionHub(),
		now:             time.Now,
		dispatchTimeout: defaultRelayDispatchTimeout,
	}
}

func (s *RelayServer) Open(ctx context.Context, stream *connect.BidiStream[runtimev1.RelayFrame, runtimev1.RelayFrame]) error {
	first, err := stream.Receive()
	if err != nil {
		if errors.Is(err, io.EOF) {
			return nil
		}
		return err
	}

	switch first.GetFrameKind() {
	case relayFrameAgentHello:
		return s.serveAgentSession(ctx, stream, first)
	case relayFrameDispatch:
		return s.serveDispatch(ctx, stream, first)
	default:
		return connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("unsupported relay frame kind: %s", first.GetFrameKind()))
	}
}

func (s *RelayServer) serveAgentSession(ctx context.Context, stream *connect.BidiStream[runtimev1.RelayFrame, runtimev1.RelayFrame], hello *runtimev1.RelayFrame) error {
	agentID := hello.GetAgentId()
	if agentID == "" {
		return connect.NewError(connect.CodeInvalidArgument, errors.New("agent relay hello missing agent_id"))
	}

	sessionID := uuid.NewString()
	connectedAt := s.now().UTC()

		// 关键设计：agent_session 只是“哪条在线流当前属于哪个 agent”的事实快照；
		// 真正的命令生命周期仍在 agent_command，session 断开只能让 relay 投递失败重试，不能直接改任务状态。
		if s.sessions != nil {
		if _, err := s.sessions.Upsert(ctx, runtimerepo.UpsertAgentSessionParams{
			AgentID:     agentID,
			RelayID:     s.relayID,
			SessionID:   sessionID,
			ConnectedAt: connectedAt,
			LastSeenAt:  connectedAt,
		}); err != nil {
			return err
		}
	}

	session := s.hub.attach(agentID, sessionID)
	defer func() {
		s.hub.detach(agentID, sessionID)
		if s.sessions != nil {
			_ = s.sessions.Delete(context.Background(), sessionID)
		}
	}()

	if err := stream.Send(&runtimev1.RelayFrame{
		FrameKind: relayFrameAgentWelcome,
		AgentId:   agentID,
		RelayId:   s.relayID,
		SessionId: sessionID,
		Accepted:  true,
	}); err != nil {
		return err
	}

	writerDone := make(chan error, 1)
	go func() {
		writerDone <- session.writeLoop(ctx, stream)
	}()

	for {
		frame, err := stream.Receive()
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}

		now := s.now().UTC()
		switch frame.GetFrameKind() {
		case relayFrameCommandResult:
			s.hub.resolve(agentID, sessionID, frame.GetCommandId(), &runtimev1.RelayFrame{
				FrameKind:    relayFrameDispatchReply,
				AgentId:      agentID,
				CommandId:    frame.GetCommandId(),
				CommandType:  frame.GetCommandType(),
				TaskId:       frame.GetTaskId(),
				ExecutionId:  frame.GetExecutionId(),
				Accepted:     frame.GetAccepted(),
				ErrorMessage: frame.GetErrorMessage(),
			})
		case relayFramePing:
			// ping 只刷新 session 可见性，不生成任何业务状态。
		default:
			continue
		}

		if s.sessions != nil {
			_ = s.sessions.Touch(ctx, sessionID, now)
		}

		select {
		case err := <-writerDone:
			return err
		default:
		}
	}
}

func (s *RelayServer) serveDispatch(ctx context.Context, stream *connect.BidiStream[runtimev1.RelayFrame, runtimev1.RelayFrame], frame *runtimev1.RelayFrame) error {
	result := s.dispatchToAgent(ctx, frame)
	return stream.Send(result)
}

func (s *RelayServer) dispatchToAgent(ctx context.Context, frame *runtimev1.RelayFrame) *runtimev1.RelayFrame {
	if frame.GetAgentId() == "" || frame.GetCommandId() == "" {
		return &runtimev1.RelayFrame{
			FrameKind:    relayFrameDispatchReply,
			AgentId:      frame.GetAgentId(),
			CommandId:    frame.GetCommandId(),
			Accepted:     false,
			ErrorMessage: "dispatch frame missing agent_id or command_id",
		}
	}

	session := s.hub.get(frame.GetAgentId())
	if session == nil {
		return &runtimev1.RelayFrame{
			FrameKind:    relayFrameDispatchReply,
			AgentId:      frame.GetAgentId(),
			CommandId:    frame.GetCommandId(),
			Accepted:     false,
			ErrorMessage: "relay session unavailable",
		}
	}

	resultCh, cancelWait := session.registerWaiter(frame.GetCommandId())
	defer cancelWait()

	if !session.enqueue(&runtimev1.RelayFrame{
		FrameKind:   relayFrameCommand,
		AgentId:     frame.GetAgentId(),
		SessionId:   session.sessionID,
		CommandId:   frame.GetCommandId(),
		CommandType: frame.GetCommandType(),
		TaskId:      frame.GetTaskId(),
		ExecutionId: frame.GetExecutionId(),
		Payload:     append([]byte(nil), frame.GetPayload()...),
	}) {
		return &runtimev1.RelayFrame{
			FrameKind:    relayFrameDispatchReply,
			AgentId:      frame.GetAgentId(),
			CommandId:    frame.GetCommandId(),
			Accepted:     false,
			ErrorMessage: "relay session closed",
		}
	}

	timer := time.NewTimer(s.dispatchTimeout)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return &runtimev1.RelayFrame{
			FrameKind:    relayFrameDispatchReply,
			AgentId:      frame.GetAgentId(),
			CommandId:    frame.GetCommandId(),
			Accepted:     false,
			ErrorMessage: ctx.Err().Error(),
		}
	case result := <-resultCh:
		return result
	case <-timer.C:
		return &runtimev1.RelayFrame{
			FrameKind:    relayFrameDispatchReply,
			AgentId:      frame.GetAgentId(),
			CommandId:    frame.GetCommandId(),
			Accepted:     false,
			ErrorMessage: "relay command ack timeout",
		}
	}
}

type relaySessionHub struct {
	mu      sync.RWMutex
	byAgent map[string]*relaySession
}

func newRelaySessionHub() *relaySessionHub {
	return &relaySessionHub{
		byAgent: map[string]*relaySession{},
	}
}

func (h *relaySessionHub) attach(agentID, sessionID string) *relaySession {
	h.mu.Lock()
	defer h.mu.Unlock()

	if existing := h.byAgent[agentID]; existing != nil {
		existing.close("relay session replaced")
	}

	session := newRelaySession(agentID, sessionID)
	h.byAgent[agentID] = session
	return session
}

func (h *relaySessionHub) get(agentID string) *relaySession {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.byAgent[agentID]
}

func (h *relaySessionHub) detach(agentID, sessionID string) {
	h.mu.Lock()
	defer h.mu.Unlock()

	session := h.byAgent[agentID]
	if session == nil || session.sessionID != sessionID {
		return
	}
	delete(h.byAgent, agentID)
	session.close("relay session closed")
}

func (h *relaySessionHub) resolve(agentID, sessionID, commandID string, result *runtimev1.RelayFrame) {
	h.mu.RLock()
	session := h.byAgent[agentID]
	h.mu.RUnlock()
	if session == nil || session.sessionID != sessionID {
		return
	}
	session.resolve(commandID, result)
}

type relaySession struct {
	agentID   string
	sessionID string

	mu      sync.Mutex
	closed  bool
	outgoing chan *runtimev1.RelayFrame
	waiters map[string]chan *runtimev1.RelayFrame
}

func newRelaySession(agentID, sessionID string) *relaySession {
	return &relaySession{
		agentID:   agentID,
		sessionID: sessionID,
		outgoing:  make(chan *runtimev1.RelayFrame, defaultRelayQueueSize),
		waiters:   map[string]chan *runtimev1.RelayFrame{},
	}
}

func (s *relaySession) enqueue(frame *runtimev1.RelayFrame) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return false
	}
	s.outgoing <- frame
	return true
}

func (s *relaySession) registerWaiter(commandID string) (<-chan *runtimev1.RelayFrame, func()) {
	s.mu.Lock()
	defer s.mu.Unlock()

	ch := make(chan *runtimev1.RelayFrame, 1)
	s.waiters[commandID] = ch
	return ch, func() {
		s.mu.Lock()
		defer s.mu.Unlock()
		delete(s.waiters, commandID)
	}
}

func (s *relaySession) resolve(commandID string, result *runtimev1.RelayFrame) {
	s.mu.Lock()
	ch := s.waiters[commandID]
	delete(s.waiters, commandID)
	s.mu.Unlock()

	if ch == nil {
		return
	}
	ch <- result
}

func (s *relaySession) close(reason string) {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return
	}
	s.closed = true
	close(s.outgoing)
	waiters := s.waiters
	s.waiters = map[string]chan *runtimev1.RelayFrame{}
	s.mu.Unlock()

	for commandID, ch := range waiters {
		ch <- &runtimev1.RelayFrame{
			FrameKind:    relayFrameDispatchReply,
			AgentId:      s.agentID,
			CommandId:    commandID,
			Accepted:     false,
			ErrorMessage: reason,
		}
	}
}

func (s *relaySession) writeLoop(ctx context.Context, stream *connect.BidiStream[runtimev1.RelayFrame, runtimev1.RelayFrame]) error {
	for {
		select {
		case <-ctx.Done():
			return nil
		case frame, ok := <-s.outgoing:
			if !ok {
				return nil
			}
			if err := stream.Send(frame); err != nil {
				return err
			}
		}
	}
}
