package runtime_domain_client

import (
	"context"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"strings"
	"sync"
	"time"

	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/connectivity"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

const (
	StateDisabled   = "disabled"
	StateConnecting = "connecting"
	StateReady      = "ready"
	StateBackoff    = "backoff"
)

var (
	ErrNotConfigured = errors.New("runtime_domain 目标未配置")
	ErrDisabled      = errors.New("runtime_domain 已禁用")
	ErrNotConnected  = errors.New("runtime_domain 未连接")
)

type StatusSnapshot struct {
	Configured          bool
	Enabled             bool
	State               string
	Target              string
	ConsecutiveFailures int64
	LastError           string
	LastConnectedAt     time.Time
	NextRetryAt         time.Time
}

type Client struct {
	target         string
	token          string
	timeout        time.Duration
	connectTimeout time.Duration
	maxBackoff     time.Duration

	mu                  sync.RWMutex
	enabled             bool
	configured          bool
	state               string
	conn                *grpc.ClientConn
	grpcClient          runtimedomainv1.RuntimeDomainClient
	consecutiveFailures int64
	lastError           string
	lastConnectedAt     time.Time
	nextRetryAt         time.Time
	forceReconnect      bool

	started bool
	cancel  context.CancelFunc
	done    chan struct{}
	wakeCh  chan struct{}
}

func New(target, token string, timeoutSec int) *Client {
	if timeoutSec <= 0 {
		timeoutSec = 5
	}
	normalizedTarget := strings.TrimSpace(target)
	configured := normalizedTarget != ""
	return &Client{
		target:         normalizedTarget,
		token:          strings.TrimSpace(token),
		timeout:        time.Duration(timeoutSec) * time.Second,
		connectTimeout: 5 * time.Second,
		maxBackoff:     30 * time.Second,
		enabled:        configured,
		configured:     configured,
		state:          StateDisabled,
		wakeCh:         make(chan struct{}, 1),
	}
}

func (c *Client) Configured() bool {
	if c == nil {
		return false
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.configured
}

func (c *Client) Enabled() bool {
	if c == nil {
		return false
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.configured && c.enabled
}

func (c *Client) Start(ctx context.Context) {
	if c == nil {
		return
	}
	c.mu.Lock()
	if !c.configured || c.started {
		c.mu.Unlock()
		return
	}
	loopCtx, cancel := context.WithCancel(ctx)
	c.cancel = cancel
	c.done = make(chan struct{})
	c.started = true
	if c.enabled {
		c.state = StateConnecting
	} else {
		c.state = StateDisabled
	}
	done := c.done
	c.mu.Unlock()

	go c.run(loopCtx, done)
	c.signalWake()
}

func (c *Client) Connect(ctx context.Context) error {
	if c == nil {
		return ErrNotConfigured
	}
	if !c.Configured() {
		return ErrNotConfigured
	}
	if !c.Enabled() {
		return ErrDisabled
	}
	c.Start(ctx)
	c.signalWake()
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("等待 runtime_domain 连接就绪失败: %w", ctx.Err())
		case <-ticker.C:
			snapshot := c.Status()
			if snapshot.State == StateReady {
				return nil
			}
		}
	}
}

func (c *Client) Close() error {
	if c == nil {
		return nil
	}
	c.mu.Lock()
	cancel := c.cancel
	done := c.done
	conn := c.conn
	c.conn = nil
	c.grpcClient = nil
	c.started = false
	c.cancel = nil
	c.done = nil
	c.forceReconnect = false
	c.state = StateDisabled
	c.nextRetryAt = time.Time{}
	c.mu.Unlock()

	if cancel != nil {
		cancel()
	}
	if done != nil {
		<-done
	}
	if conn != nil {
		return conn.Close()
	}
	return nil
}

func (c *Client) Enable() error {
	if c == nil || !c.Configured() {
		return ErrNotConfigured
	}
	c.mu.Lock()
	c.enabled = true
	if c.state == StateDisabled {
		c.state = StateConnecting
	}
	c.mu.Unlock()
	c.signalWake()
	return nil
}

func (c *Client) Disable() error {
	if c == nil || !c.Configured() {
		return ErrNotConfigured
	}
	c.mu.Lock()
	c.enabled = false
	c.forceReconnect = false
	c.state = StateDisabled
	c.nextRetryAt = time.Time{}
	conn := c.conn
	c.conn = nil
	c.grpcClient = nil
	c.mu.Unlock()
	if conn != nil {
		_ = conn.Close()
	}
	c.signalWake()
	return nil
}

func (c *Client) Reconnect() error {
	if c == nil || !c.Configured() {
		return ErrNotConfigured
	}
	if !c.Enabled() {
		return ErrDisabled
	}
	c.mu.Lock()
	c.forceReconnect = true
	c.mu.Unlock()
	c.signalWake()
	return nil
}

func (c *Client) Status() StatusSnapshot {
	if c == nil {
		return StatusSnapshot{}
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return StatusSnapshot{
		Configured:          c.configured,
		Enabled:             c.enabled,
		State:               c.state,
		Target:              c.target,
		ConsecutiveFailures: c.consecutiveFailures,
		LastError:           c.lastError,
		LastConnectedAt:     c.lastConnectedAt,
		NextRetryAt:         c.nextRetryAt,
	}
}

func (c *Client) GetBranchHead(ctx context.Context, branchID string) (*runtimedomainv1.GetBranchHeadResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.GetBranchHead(callCtx, &runtimedomainv1.GetBranchHeadRequest{BranchId: branchID})
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) CountNewLabelsSinceCommit(
	ctx context.Context,
	projectID string,
	branchID string,
	sinceCommitID string,
) (*runtimedomainv1.CountNewLabelsSinceCommitResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.CountNewLabelsSinceCommit(callCtx, &runtimedomainv1.CountNewLabelsSinceCommitRequest{
		ProjectId:     projectID,
		BranchId:      branchID,
		SinceCommitId: sinceCommitID,
	})
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) ResolveRoundReveal(
	ctx context.Context,
	loopID string,
	roundID string,
	branchID string,
	force bool,
	minRequired int32,
) (*runtimedomainv1.ResolveRoundRevealResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.ResolveRoundReveal(callCtx, &runtimedomainv1.ResolveRoundRevealRequest{
		LoopId:      loopID,
		RoundId:     roundID,
		BranchId:    branchID,
		Force:       force,
		MinRequired: minRequired,
	})
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) ActivateSamples(
	ctx context.Context,
	req *runtimedomainv1.ActivateSamplesRequest,
) (*runtimedomainv1.ActivateSamplesResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.ActivateSamples(callCtx, req)
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) AdvanceBranchHead(
	ctx context.Context,
	commandID string,
	branchID string,
	toCommitID string,
	reason string,
) (*runtimedomainv1.AdvanceBranchHeadResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.AdvanceBranchHead(callCtx, &runtimedomainv1.AdvanceBranchHeadRequest{
		CommandId:  commandID,
		BranchId:   branchID,
		ToCommitId: toCommitID,
		Reason:     reason,
	})
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) QueryData(
	ctx context.Context,
	req *runtimedomainv1.DataRequest,
) ([]*runtimedomainv1.DataResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()

	stream, callErr := client.QueryData(callCtx, req)
	if callErr != nil {
		c.handleCallError(callErr)
		return nil, callErr
	}

	responses := make([]*runtimedomainv1.DataResponse, 0, 1)
	for {
		resp, recvErr := stream.Recv()
		if recvErr == io.EOF {
			break
		}
		if recvErr != nil {
			c.handleCallError(recvErr)
			return nil, recvErr
		}
		responses = append(responses, resp)
	}
	c.handleCallError(nil)
	return responses, nil
}

func (c *Client) CreateUploadTicket(
	ctx context.Context,
	req *runtimedomainv1.UploadTicketRequest,
) (*runtimedomainv1.UploadTicketResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.CreateUploadTicket(callCtx, req)
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) CreateDownloadTicket(
	ctx context.Context,
	req *runtimedomainv1.DownloadTicketRequest,
) (*runtimedomainv1.DownloadTicketResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.CreateDownloadTicket(callCtx, req)
	c.handleCallError(callErr)
	return resp, callErr
}

func (c *Client) CreateRuntimeReleaseDownloadTicket(
	ctx context.Context,
	req *runtimedomainv1.RuntimeReleaseDownloadTicketRequest,
) (*runtimedomainv1.RuntimeReleaseDownloadTicketResponse, error) {
	client, token, timeout, err := c.clientForCall()
	if err != nil {
		return nil, err
	}
	callCtx, cancel := context.WithTimeout(withToken(ctx, token), timeout)
	defer cancel()
	resp, callErr := client.CreateRuntimeReleaseDownloadTicket(callCtx, req)
	c.handleCallError(callErr)
	return resp, callErr
}

func IsTransientError(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, ErrDisabled) || errors.Is(err, ErrNotConnected) {
		return true
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		return true
	}
	switch status.Code(err) {
	case
		codes.Unavailable,
		codes.DeadlineExceeded,
		codes.Canceled,
		codes.ResourceExhausted,
		codes.Aborted,
		codes.Internal:
		return true
	default:
		return false
	}
}

func IsNotFoundError(err error) bool {
	if err == nil {
		return false
	}
	return status.Code(err) == codes.NotFound
}

func IsInvalidRequestError(err error) bool {
	if err == nil {
		return false
	}
	switch status.Code(err) {
	case codes.InvalidArgument, codes.FailedPrecondition:
		return true
	default:
		return false
	}
}

func withToken(ctx context.Context, token string) context.Context {
	if strings.TrimSpace(token) == "" {
		return ctx
	}
	return metadata.AppendToOutgoingContext(ctx, "x-internal-token", token)
}

func (c *Client) run(ctx context.Context, done chan struct{}) {
	defer close(done)
	backoff := time.Second
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		snapshot := c.Status()
		if !snapshot.Configured {
			return
		}
		if !snapshot.Enabled {
			c.setState(StateDisabled)
			if !c.waitOrWake(ctx, 0) {
				return
			}
			continue
		}

		conn := c.currentConn()
		if conn == nil {
			c.setState(StateConnecting)
			err := c.establishConnection(ctx)
			if err != nil {
				delay := withJitter(backoff)
				c.recordFailure(err, delay)
				if !c.waitOrWake(ctx, delay) {
					return
				}
				backoff = minDuration(backoff*2, c.maxBackoff)
				continue
			}
			backoff = time.Second
			c.markReady()
			continue
		}

		if c.consumeForceReconnect() {
			c.resetConnection("收到重连命令")
			continue
		}

		switch conn.GetState() {
		case connectivity.Ready:
			c.markReady()
			waitCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
			_ = conn.WaitForStateChange(waitCtx, connectivity.Ready)
			cancel()
		case connectivity.Idle:
			c.setState(StateConnecting)
			conn.Connect()
			if !c.waitOrWake(ctx, 500*time.Millisecond) {
				return
			}
		case connectivity.Connecting:
			c.setState(StateConnecting)
			if !c.waitOrWake(ctx, 500*time.Millisecond) {
				return
			}
		case connectivity.TransientFailure:
			c.resetConnection("连接进入退避状态")
		case connectivity.Shutdown:
			c.resetConnection("连接已关闭")
		}
	}
}

func (c *Client) establishConnection(ctx context.Context) error {
	conn, err := grpc.NewClient(c.target, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return fmt.Errorf("创建 runtime_domain 客户端失败: %w", err)
	}
	conn.Connect()

	dialCtx, cancel := context.WithTimeout(ctx, c.connectTimeout)
	defer cancel()
	if err := waitUntilReady(dialCtx, conn); err != nil {
		_ = conn.Close()
		return fmt.Errorf("连接 runtime_domain 失败: %w", err)
	}

	c.mu.Lock()
	c.conn = conn
	c.grpcClient = runtimedomainv1.NewRuntimeDomainClient(conn)
	c.mu.Unlock()
	return nil
}

func waitUntilReady(ctx context.Context, conn *grpc.ClientConn) error {
	for {
		state := conn.GetState()
		switch state {
		case connectivity.Ready:
			return nil
		case connectivity.Shutdown:
			return errors.New("连接已关闭")
		}
		if !conn.WaitForStateChange(ctx, state) {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			return errors.New("连接状态未变化")
		}
	}
}

func (c *Client) recordFailure(err error, delay time.Duration) {
	now := time.Now().UTC()
	c.mu.Lock()
	c.consecutiveFailures++
	c.lastError = strings.TrimSpace(err.Error())
	c.state = StateBackoff
	c.nextRetryAt = now.Add(delay)
	c.conn = nil
	c.grpcClient = nil
	c.mu.Unlock()
}

func (c *Client) markReady() {
	c.mu.Lock()
	c.state = StateReady
	c.lastConnectedAt = time.Now().UTC()
	c.nextRetryAt = time.Time{}
	c.lastError = ""
	c.consecutiveFailures = 0
	c.mu.Unlock()
}

func (c *Client) setState(next string) {
	c.mu.Lock()
	c.state = next
	if next != StateBackoff {
		c.nextRetryAt = time.Time{}
	}
	c.mu.Unlock()
}

func (c *Client) currentConn() *grpc.ClientConn {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.conn
}

func (c *Client) consumeForceReconnect() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.forceReconnect {
		return false
	}
	c.forceReconnect = false
	return true
}

func (c *Client) resetConnection(reason string) {
	c.mu.Lock()
	conn := c.conn
	c.conn = nil
	c.grpcClient = nil
	if strings.TrimSpace(reason) != "" {
		c.lastError = strings.TrimSpace(reason)
	}
	c.state = StateConnecting
	c.nextRetryAt = time.Time{}
	c.mu.Unlock()
	if conn != nil {
		_ = conn.Close()
	}
	c.signalWake()
}

func (c *Client) signalWake() {
	if c == nil {
		return
	}
	select {
	case c.wakeCh <- struct{}{}:
	default:
	}
}

func (c *Client) waitOrWake(ctx context.Context, timeout time.Duration) bool {
	if timeout <= 0 {
		select {
		case <-ctx.Done():
			return false
		case <-c.wakeCh:
			return true
		}
	}

	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-c.wakeCh:
		return true
	case <-timer.C:
		return true
	}
}

func withJitter(base time.Duration) time.Duration {
	if base <= 0 {
		return 100 * time.Millisecond
	}
	limit := int64(base / 4)
	if limit <= 0 {
		limit = int64(250 * time.Millisecond)
	}
	return base + time.Duration(rand.Int63n(limit+1))
}

func minDuration(a time.Duration, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}

func (c *Client) clientForCall() (runtimedomainv1.RuntimeDomainClient, string, time.Duration, error) {
	if c == nil || !c.Configured() {
		return nil, "", 0, ErrNotConfigured
	}
	if !c.Enabled() {
		return nil, "", 0, ErrDisabled
	}
	c.mu.RLock()
	client := c.grpcClient
	token := c.token
	timeout := c.timeout
	c.mu.RUnlock()
	if client == nil {
		return nil, "", 0, ErrNotConnected
	}
	return client, token, timeout, nil
}

func (c *Client) handleCallError(callErr error) {
	if !IsTransientError(callErr) {
		return
	}
	if callErr != nil {
		c.mu.Lock()
		c.lastError = strings.TrimSpace(callErr.Error())
		c.mu.Unlock()
	}
	c.resetConnection("检测到连接异常，准备重连")
}
