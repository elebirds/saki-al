package runtimeclient

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"
	"github.com/spf13/cast"
	"google.golang.org/grpc"
	"google.golang.org/grpc/connectivity"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-agent/internal/agent"
	"github.com/elebirds/saki/saki-agent/internal/device"
	runtimecontrolv1 "github.com/elebirds/saki/saki-agent/internal/gen/runtimecontrolv1"
	"github.com/elebirds/saki/saki-agent/internal/pluginloader"
)

const (
	StateDisabled   = "disabled"
	StateConnecting = "connecting"
	StateReady      = "ready"
	StateBackoff    = "backoff"

	defaultStubStepDuration = 2 * time.Second
	outgoingQueueSize       = 256
)

var (
	ErrNotConfigured = errors.New("runtime_control 目标未配置")
	ErrNotConnected  = errors.New("runtime_control 未连接")
	errReconnect     = errors.New("reconnect requested")
)

type Config struct {
	Target            string
	Token             string
	ExecutorID        string
	NodeID            string
	Version           string
	RuntimeKind       string
	KernelsDir        string
	HeartbeatInterval time.Duration
	ConnectTimeout    time.Duration
	InitialBackoff    time.Duration
	MaxBackoff        time.Duration
}

type StatusSnapshot struct {
	Configured          bool
	State               string
	Target              string
	ExecutorID          string
	NodeID              string
	Busy                bool
	CurrentStepID       string
	ConsecutiveFailures int64
	LastError           string
	LastConnectedAt     time.Time
	NextRetryAt         time.Time
	PluginCatalogLoaded bool
	PluginCatalogSize   int
	PluginCatalogAt     time.Time
	PluginCatalogError  string
	Plugins             []PluginSnapshot
}

type PluginSnapshot struct {
	ID                   string
	Version              string
	DisplayName          string
	SourcePath           string
	SupportsAutoFallback bool
}

type runningStep struct {
	stepID           string
	kernelInstanceID string
	cancel           context.CancelFunc
	done             chan struct{}
	seq              int64
	stopReason       string
	stopForce        bool
}

type Client struct {
	cfg    Config
	daemon *agent.Agent
	logger zerolog.Logger

	mu                  sync.RWMutex
	configured          bool
	state               string
	conn                *grpc.ClientConn
	consecutiveFailures int64
	lastError           string
	lastConnectedAt     time.Time
	nextRetryAt         time.Time

	started bool
	cancel  context.CancelFunc
	done    chan struct{}
	wakeCh  chan struct{}

	stepMu      sync.Mutex
	runningStep *runningStep
	outgoingCh  chan *runtimecontrolv1.RuntimeMessage

	pluginMu              sync.RWMutex
	pluginCatalogLoaded   bool
	pluginCatalogAt       time.Time
	pluginCatalogError    string
	pluginCatalogSnapshot []pluginloader.PluginSpec
}

func New(cfg Config, daemon *agent.Agent, logger zerolog.Logger) *Client {
	target := strings.TrimSpace(cfg.Target)
	executorID := strings.TrimSpace(cfg.ExecutorID)
	if executorID == "" {
		// 默认值仅为开发便利；生产建议显式配置稳定 executor_id。
		executorID = defaultID("agent")
	}
	nodeID := strings.TrimSpace(cfg.NodeID)
	if nodeID == "" {
		// node_id 默认与主机名一致，用于节点归属，不影响调度主键语义。
		nodeID = defaultID("node")
	}
	version := strings.TrimSpace(cfg.Version)
	if version == "" {
		version = "dev"
	}
	runtimeKind := strings.TrimSpace(cfg.RuntimeKind)
	if runtimeKind == "" {
		runtimeKind = "saki-agent"
	}
	heartbeatInterval := cfg.HeartbeatInterval
	if heartbeatInterval <= 0 {
		heartbeatInterval = 10 * time.Second
	}
	connectTimeout := cfg.ConnectTimeout
	if connectTimeout <= 0 {
		connectTimeout = 5 * time.Second
	}
	initialBackoff := cfg.InitialBackoff
	if initialBackoff <= 0 {
		initialBackoff = 2 * time.Second
	}
	maxBackoff := cfg.MaxBackoff
	if maxBackoff <= 0 {
		maxBackoff = 30 * time.Second
	}
	if maxBackoff < initialBackoff {
		maxBackoff = initialBackoff
	}
	return &Client{
		cfg: Config{
			Target:            target,
			Token:             strings.TrimSpace(cfg.Token),
			ExecutorID:        executorID,
			NodeID:            nodeID,
			Version:           version,
			RuntimeKind:       runtimeKind,
			KernelsDir:        strings.TrimSpace(cfg.KernelsDir),
			HeartbeatInterval: heartbeatInterval,
			ConnectTimeout:    connectTimeout,
			InitialBackoff:    initialBackoff,
			MaxBackoff:        maxBackoff,
		},
		daemon:     daemon,
		logger:     logger,
		configured: target != "",
		state:      StateDisabled,
		wakeCh:     make(chan struct{}, 1),
		outgoingCh: make(chan *runtimecontrolv1.RuntimeMessage, outgoingQueueSize),
	}
}

func (c *Client) Start(ctx context.Context) {
	if c == nil {
		return
	}
	c.mu.Lock()
	if c.started {
		c.mu.Unlock()
		return
	}
	loopCtx, cancel := context.WithCancel(ctx)
	c.cancel = cancel
	c.done = make(chan struct{})
	c.started = true
	if c.configured {
		c.state = StateConnecting
	} else {
		c.state = StateDisabled
	}
	done := c.done
	c.mu.Unlock()

	if !c.configured {
		c.logger.Warn().Msg("RUNTIME_CONTROL_TARGET 为空，dispatcher 流式连接未启用")
		close(done)
		return
	}

	if _, err := c.ensurePluginCatalogLoaded(); err != nil {
		c.logger.Warn().Err(err).Msg("插件目录初始化失败，agent 将以上次缓存/空清单继续运行")
	}

	go c.run(loopCtx, done)
}

func (c *Client) Close() error {
	if c == nil {
		return nil
	}
	c.mu.Lock()
	cancel := c.cancel
	done := c.done
	conn := c.conn
	c.cancel = nil
	c.done = nil
	c.conn = nil
	c.started = false
	c.state = StateDisabled
	c.mu.Unlock()

	c.abortRunningStep()

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

func (c *Client) Reconnect() error {
	if c == nil || !c.configured {
		return ErrNotConfigured
	}
	c.signalWake()
	c.logger.Info().Msg("已请求 runtime_control 重连")
	return nil
}

func (c *Client) Status() StatusSnapshot {
	if c == nil {
		return StatusSnapshot{}
	}
	c.mu.RLock()
	snapshot := StatusSnapshot{
		Configured:          c.configured,
		State:               c.state,
		Target:              c.cfg.Target,
		ExecutorID:          c.cfg.ExecutorID,
		NodeID:              c.cfg.NodeID,
		ConsecutiveFailures: c.consecutiveFailures,
		LastError:           c.lastError,
		LastConnectedAt:     c.lastConnectedAt,
		NextRetryAt:         c.nextRetryAt,
	}
	c.mu.RUnlock()
	busy, stepID := c.currentStepSnapshot()
	snapshot.Busy = busy
	snapshot.CurrentStepID = stepID
	loaded, loadedAt, loadErr, plugins := c.pluginCatalogStatusSnapshot()
	snapshot.PluginCatalogLoaded = loaded
	snapshot.PluginCatalogSize = len(plugins)
	snapshot.PluginCatalogAt = loadedAt
	snapshot.PluginCatalogError = loadErr
	snapshot.Plugins = plugins
	return snapshot
}

func (c *Client) run(ctx context.Context, done chan struct{}) {
	defer close(done)
	backoff := c.cfg.InitialBackoff
	for {
		if ctx.Err() != nil {
			c.setState(StateDisabled)
			return
		}

		c.setState(StateConnecting)
		conn, stream, err := c.connect(ctx)
		if err != nil {
			c.recordFailure(err, backoff)
			if !c.waitOrWake(ctx, backoff) {
				c.setState(StateDisabled)
				return
			}
			backoff = minDuration(backoff*2, c.cfg.MaxBackoff)
			continue
		}

		c.mu.Lock()
		c.conn = conn
		c.lastConnectedAt = time.Now().UTC()
		c.consecutiveFailures = 0
		c.lastError = ""
		c.nextRetryAt = time.Time{}
		c.state = StateReady
		c.mu.Unlock()

		c.logger.Info().
			Str("target", c.cfg.Target).
			Str("executor_id", c.cfg.ExecutorID).
			Str("node_id", c.cfg.NodeID).
			Msg("dispatcher stream 已连接")

		runErr := c.runStream(ctx, stream)
		if runErr != nil && !errors.Is(runErr, context.Canceled) && !errors.Is(runErr, io.EOF) {
			c.logger.Warn().Err(runErr).Msg("dispatcher stream 中断，准备重连")
		}
		c.abortRunningStep()
		c.drainOutgoingQueue()
		_ = conn.Close()

		c.mu.Lock()
		c.conn = nil
		c.mu.Unlock()

		if ctx.Err() != nil {
			c.setState(StateDisabled)
			return
		}
		if errors.Is(runErr, errReconnect) {
			backoff = c.cfg.InitialBackoff
			continue
		}
		backoff = minDuration(backoff*2, c.cfg.MaxBackoff)
		c.recordFailure(runErr, backoff)
		if !c.waitOrWake(ctx, backoff) {
			c.setState(StateDisabled)
			return
		}
	}
}

func (c *Client) connect(
	ctx context.Context,
) (*grpc.ClientConn, grpc.BidiStreamingClient[runtimecontrolv1.RuntimeMessage, runtimecontrolv1.RuntimeMessage], error) {
	dialCtx, cancel := context.WithTimeout(ctx, c.cfg.ConnectTimeout)
	defer cancel()

	conn, err := grpc.DialContext(
		dialCtx,
		c.cfg.Target,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return nil, nil, fmt.Errorf("dial dispatcher failed: %w", err)
	}
	client := runtimecontrolv1.NewRuntimeControlClient(conn)
	streamCtx := withToken(ctx, c.cfg.Token)
	stream, err := client.Stream(streamCtx)
	if err != nil {
		_ = conn.Close()
		return nil, nil, fmt.Errorf("open stream failed: %w", err)
	}
	return conn, stream, nil
}

func (c *Client) runStream(
	ctx context.Context,
	stream grpc.BidiStreamingClient[runtimecontrolv1.RuntimeMessage, runtimecontrolv1.RuntimeMessage],
) error {
	c.drainOutgoingQueue()
	registerMessage, resources, err := c.buildRegisterMessage()
	if err != nil {
		return err
	}
	if err := stream.Send(registerMessage); err != nil {
		return fmt.Errorf("send register failed: %w", err)
	}

	recvCh := make(chan *runtimecontrolv1.RuntimeMessage, 64)
	recvErrCh := make(chan error, 1)
	go func() {
		for {
			message, recvErr := stream.Recv()
			if recvErr != nil {
				recvErrCh <- recvErr
				return
			}
			recvCh <- message
		}
	}()

	heartbeatTicker := time.NewTicker(c.cfg.HeartbeatInterval)
	defer heartbeatTicker.Stop()

	startedAt := time.Now().UTC()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-recvErrCh:
			return err
		case <-heartbeatTicker.C:
			heartbeat := c.buildHeartbeatMessage(resources, startedAt)
			if err := stream.Send(heartbeat); err != nil {
				return fmt.Errorf("send heartbeat failed: %w", err)
			}
		case incoming := <-recvCh:
			outgoing, reconnect := c.handleIncoming(ctx, incoming)
			for _, message := range outgoing {
				if message == nil {
					continue
				}
				if err := stream.Send(message); err != nil {
					return fmt.Errorf("send response failed: %w", err)
				}
			}
			if reconnect {
				return errReconnect
			}
		case queued := <-c.outgoingCh:
			if queued == nil {
				continue
			}
			if err := stream.Send(queued); err != nil {
				return fmt.Errorf("send queued response failed: %w", err)
			}
		case <-c.wakeCh:
			return errReconnect
		}
	}
}

func (c *Client) buildRegisterMessage() (*runtimecontrolv1.RuntimeMessage, *runtimecontrolv1.ResourceSummary, error) {
	capabilities, err := device.DetectDeviceCapabilities()
	if err != nil {
		c.logger.Warn().Err(err).Msg("硬件探测失败，使用最小能力注册")
		capabilities = &device.DeviceCapabilities{
			Platform: "unknown",
			CPU: &device.CPUInfo{
				PhysicalCores: 1,
				LogicalCores:  1,
				ModelName:     "unknown",
				Architecture:  "unknown",
			},
		}
	}
	resources := resourceSummaryFromCapabilities(capabilities)
	hardwareProfile, _ := structpb.NewStruct(hardwareProfileMap(capabilities))
	mpsProfile, _ := structpb.NewStruct(mpsStabilityProfileMap(capabilities))
	compatFlags, _ := structpb.NewStruct(kernelCompatFlagsMap(capabilities))

	plugins, _ := c.loadPlugins(resources)

	register := &runtimecontrolv1.Register{
		RequestId:           uuid.NewString(),
		ExecutorId:          c.cfg.ExecutorID,
		Version:             c.cfg.Version,
		Plugins:             plugins,
		Resources:           resources,
		NodeId:              c.cfg.NodeID,
		HardwareProfile:     hardwareProfile,
		MpsStabilityProfile: mpsProfile,
		KernelCompatFlags:   compatFlags,
		RuntimeKind:         c.cfg.RuntimeKind,
	}
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_Register{Register: register},
	}, resources, nil
}

func (c *Client) loadPlugins(resources *runtimecontrolv1.ResourceSummary) ([]*runtimecontrolv1.PluginCapability, error) {
	items, err := c.ensurePluginCatalogLoaded()
	if len(items) == 0 {
		return nil, err
	}
	accelerators := resourcesToSupportedAccelerators(resources)
	plugins := make([]*runtimecontrolv1.PluginCapability, 0, len(items))
	for _, item := range items {
		requestSchema, schemaErr := structpb.NewStruct(item.RequestConfigSchema)
		if schemaErr != nil {
			requestSchema = &structpb.Struct{Fields: map[string]*structpb.Value{}}
		}
		defaultConfig, defaultErr := structpb.NewStruct(item.DefaultRequestConfig)
		if defaultErr != nil {
			defaultConfig = &structpb.Struct{Fields: map[string]*structpb.Value{}}
		}
		plugins = append(plugins, &runtimecontrolv1.PluginCapability{
			PluginId:              item.ID,
			Version:               item.Version,
			SupportedStepTypes:    item.SupportedStepTypes,
			SupportedStrategies:   item.SupportedStrategies,
			DisplayName:           item.DisplayName,
			SupportedAccelerators: accelerators,
			SupportsAutoFallback:  item.SupportsAutoFallback,
			RequestConfigSchema:   requestSchema,
			DefaultRequestConfig:  defaultConfig,
		})
	}
	return plugins, err
}

func (c *Client) ensurePluginCatalogLoaded() ([]pluginloader.PluginSpec, error) {
	c.pluginMu.RLock()
	if c.pluginCatalogLoaded {
		items := clonePluginSpecs(c.pluginCatalogSnapshot)
		loadErr := errorFromText(c.pluginCatalogError)
		c.pluginMu.RUnlock()
		return items, loadErr
	}
	c.pluginMu.RUnlock()

	c.pluginMu.Lock()
	defer c.pluginMu.Unlock()

	if c.pluginCatalogLoaded {
		return clonePluginSpecs(c.pluginCatalogSnapshot), errorFromText(c.pluginCatalogError)
	}

	kernelsDir := strings.TrimSpace(c.cfg.KernelsDir)
	started := time.Now()
	c.logger.Info().Str("kernels_dir", kernelsDir).Msg("开始扫描 kernel 插件清单")

	var (
		items   []pluginloader.PluginSpec
		loadErr error
	)
	switch {
	case kernelsDir == "":
		loadErr = errors.New("kernels_dir 为空")
	default:
		info, statErr := os.Stat(kernelsDir)
		if statErr != nil {
			loadErr = fmt.Errorf("检查 kernels_dir 失败: %w", statErr)
			break
		}
		if !info.IsDir() {
			loadErr = fmt.Errorf("kernels_dir 不是目录: %s", kernelsDir)
			break
		}
		items, loadErr = pluginloader.LoadFromDir(kernelsDir)
	}

	c.pluginCatalogSnapshot = clonePluginSpecs(items)
	c.pluginCatalogLoaded = true
	c.pluginCatalogAt = time.Now().UTC()
	c.pluginCatalogError = ""
	if loadErr != nil {
		c.pluginCatalogError = loadErr.Error()
	}

	elapsed := time.Since(started)
	if loadErr != nil {
		c.logger.Warn().
			Err(loadErr).
			Str("kernels_dir", kernelsDir).
			Int("plugin_count", len(c.pluginCatalogSnapshot)).
			Dur("elapsed", elapsed).
			Msg("扫描 kernel 插件清单完成（包含错误）")
	} else {
		c.logger.Info().
			Str("kernels_dir", kernelsDir).
			Int("plugin_count", len(c.pluginCatalogSnapshot)).
			Dur("elapsed", elapsed).
			Msg("扫描 kernel 插件清单完成")
	}
	if len(c.pluginCatalogSnapshot) == 0 {
		c.logger.Warn().Str("kernels_dir", kernelsDir).Msg("未加载到任何插件能力，dispatcher 将无法派发业务 step")
	}
	for _, item := range c.pluginCatalogSnapshot {
		c.logger.Info().
			Str("plugin_id", item.ID).
			Str("version", item.Version).
			Str("display_name", item.DisplayName).
			Str("source", item.SourcePath).
			Strs("supported_step_types", item.SupportedStepTypes).
			Strs("supported_strategies", item.SupportedStrategies).
			Bool("supports_auto_fallback", item.SupportsAutoFallback).
			Msg("插件已加载并常驻内存")
	}

	return clonePluginSpecs(c.pluginCatalogSnapshot), loadErr
}

func (c *Client) pluginCatalogStatusSnapshot() (bool, time.Time, string, []PluginSnapshot) {
	c.pluginMu.RLock()
	defer c.pluginMu.RUnlock()

	if !c.pluginCatalogLoaded {
		return false, time.Time{}, "", nil
	}
	plugins := make([]PluginSnapshot, 0, len(c.pluginCatalogSnapshot))
	for _, item := range c.pluginCatalogSnapshot {
		plugins = append(plugins, PluginSnapshot{
			ID:                   item.ID,
			Version:              item.Version,
			DisplayName:          item.DisplayName,
			SourcePath:           item.SourcePath,
			SupportsAutoFallback: item.SupportsAutoFallback,
		})
	}
	return true, c.pluginCatalogAt, c.pluginCatalogError, plugins
}

func (c *Client) buildHeartbeatMessage(resources *runtimecontrolv1.ResourceSummary, startedAt time.Time) *runtimecontrolv1.RuntimeMessage {
	status := "READY"
	busy, currentStepID := c.currentStepSnapshot()
	runDir := ""
	cacheDir := ""
	if c.daemon != nil {
		runDir = c.daemon.RunDir()
		cacheDir = c.daemon.CacheDir()
	}
	if c.daemon != nil && c.daemon.IsDraining() {
		status = "DRAINING"
	} else if busy {
		status = "BUSY"
	}
	healthDetail, _ := structpb.NewStruct(map[string]any{
		"run_dir":    runDir,
		"cache_dir":  cacheDir,
		"conn_state": c.connState(),
	})
	heartbeat := &runtimecontrolv1.Heartbeat{
		RequestId:     uuid.NewString(),
		ExecutorId:    c.cfg.ExecutorID,
		Busy:          busy,
		CurrentStepId: currentStepID,
		Resources:     resources,
		NodeId:        c.cfg.NodeID,
		HealthStatus:  status,
		HealthDetail:  healthDetail,
		UptimeSec:     int64(time.Since(startedAt).Seconds()),
	}
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_Heartbeat{Heartbeat: heartbeat},
	}
}

func (c *Client) handleIncoming(ctx context.Context, message *runtimecontrolv1.RuntimeMessage) ([]*runtimecontrolv1.RuntimeMessage, bool) {
	if message == nil {
		return nil, false
	}
	switch payload := message.GetPayload().(type) {
	case *runtimecontrolv1.RuntimeMessage_Ack:
		ack := payload.Ack
		c.logger.Debug().
			Str("ack_for", ack.GetAckFor()).
			Str("status", ack.GetStatus().String()).
			Str("type", ack.GetType().String()).
			Str("reason", ack.GetReason().String()).
			Msg("收到 dispatcher ack")
		return nil, false
	case *runtimecontrolv1.RuntimeMessage_AssignStep:
		return c.handleAssign(ctx, payload.AssignStep), false
	case *runtimecontrolv1.RuntimeMessage_StopStep:
		return c.handleStop(payload.StopStep), false
	case *runtimecontrolv1.RuntimeMessage_Error:
		errPayload := payload.Error
		c.logger.Warn().
			Str("code", errPayload.GetCode()).
			Str("message", errPayload.GetMessage()).
			Str("reply_to", errPayload.GetReplyTo()).
			Msg("收到 dispatcher error")
		return nil, false
	default:
		c.logger.Warn().Str("payload", fmt.Sprintf("%T", payload)).Msg("收到未处理的消息类型")
	}
	return nil, false
}

func (c *Client) handleAssign(ctx context.Context, assign *runtimecontrolv1.AssignStep) []*runtimecontrolv1.RuntimeMessage {
	if assign == nil {
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck("", runtimecontrolv1.AckStatus_ERROR, runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP, runtimecontrolv1.AckReason_ACK_REASON_REJECTED, "assign 请求为空"),
		}
	}
	if assign.GetStep() == nil {
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck(assign.GetRequestId(), runtimecontrolv1.AckStatus_ERROR, runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP, runtimecontrolv1.AckReason_ACK_REASON_REJECTED, "assign 请求缺少 step 负载"),
		}
	}
	stepID := strings.TrimSpace(assign.GetStep().GetStepId())
	if stepID == "" {
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck(assign.GetRequestId(), runtimecontrolv1.AckStatus_ERROR, runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP, runtimecontrolv1.AckReason_ACK_REASON_REJECTED, "step_id 不能为空"),
		}
	}
	if c.daemon != nil && c.daemon.IsDraining() {
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck(assign.GetRequestId(), runtimecontrolv1.AckStatus_ERROR, runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP, runtimecontrolv1.AckReason_ACK_REASON_STOPPING, "agent 处于 DRAINING，拒绝新任务"),
		}
	}

	kernelInstanceID := fmt.Sprintf("%s:%s", c.cfg.ExecutorID, stepID)
	stepCtx, cancel := context.WithCancel(ctx)
	c.stepMu.Lock()
	if c.runningStep != nil {
		c.stepMu.Unlock()
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck(assign.GetRequestId(), runtimecontrolv1.AckStatus_ERROR, runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP, runtimecontrolv1.AckReason_ACK_REASON_EXECUTOR_BUSY, "当前已有运行中的 step"),
		}
	}
	running := &runningStep{
		stepID:           stepID,
		kernelInstanceID: kernelInstanceID,
		cancel:           cancel,
		done:             make(chan struct{}),
	}
	c.runningStep = running
	seq := c.nextSeqLocked(running)
	c.stepMu.Unlock()

	go c.runAssignedStep(stepCtx, running, assign.GetStep())
	return []*runtimecontrolv1.RuntimeMessage{
		c.buildAck(assign.GetRequestId(), runtimecontrolv1.AckStatus_OK, runtimecontrolv1.AckType_ACK_TYPE_ASSIGN_STEP, runtimecontrolv1.AckReason_ACK_REASON_ACCEPTED, "step 已接收"),
		c.buildStatusEvent(stepID, seq, runtimecontrolv1.RuntimeStepStatus_RUNNING, "step 已启动（占位执行）", kernelInstanceID),
	}
}

func (c *Client) handleStop(stop *runtimecontrolv1.StopStep) []*runtimecontrolv1.RuntimeMessage {
	if stop == nil {
		return nil
	}
	stepID := strings.TrimSpace(stop.GetStepId())
	if stepID == "" {
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck(stop.GetRequestId(), runtimecontrolv1.AckStatus_ERROR, runtimecontrolv1.AckType_ACK_TYPE_STOP_STEP, runtimecontrolv1.AckReason_ACK_REASON_REJECTED, "step_id 不能为空"),
		}
	}

	c.stepMu.Lock()
	running := c.runningStep
	if running == nil || running.stepID != stepID {
		c.stepMu.Unlock()
		return []*runtimecontrolv1.RuntimeMessage{
			c.buildAck(stop.GetRequestId(), runtimecontrolv1.AckStatus_OK, runtimecontrolv1.AckType_ACK_TYPE_STOP_STEP, runtimecontrolv1.AckReason_ACK_REASON_STEP_NOT_RUNNING, "当前无运行中的 step"),
		}
	}
	reason := strings.TrimSpace(stop.GetReason())
	if reason == "" {
		reason = "收到 stop 请求"
	}
	running.stopReason = reason
	running.stopForce = stop.GetForce()
	cancel := running.cancel
	c.stepMu.Unlock()
	cancel()
	return []*runtimecontrolv1.RuntimeMessage{
		c.buildAck(stop.GetRequestId(), runtimecontrolv1.AckStatus_OK, runtimecontrolv1.AckType_ACK_TYPE_STOP_STEP, runtimecontrolv1.AckReason_ACK_REASON_STOPPING, "已触发 step 停止"),
	}
}

func (c *Client) runAssignedStep(ctx context.Context, running *runningStep, step *runtimecontrolv1.StepPayload) {
	defer close(running.done)
	duration := c.resolveStubDuration(step)
	timer := time.NewTimer(duration)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		c.completeRunningStep(running, true)
	case <-timer.C:
		c.completeRunningStep(running, false)
	}
}

func (c *Client) completeRunningStep(running *runningStep, cancelled bool) {
	c.stepMu.Lock()
	if c.runningStep != running {
		c.stepMu.Unlock()
		return
	}
	c.runningStep = nil
	statusSeq := c.nextSeqLocked(running)
	stepID := running.stepID
	kernelInstanceID := running.kernelInstanceID
	stopReason := strings.TrimSpace(running.stopReason)
	stopForce := running.stopForce
	c.stepMu.Unlock()

	if cancelled {
		if stopReason == "" {
			stopReason = "step 已停止"
		}
		runtimeMeta := map[string]any{
			"runtime_kind": c.cfg.RuntimeKind,
			"reason":       "stopped",
			"force":        stopForce,
		}
		c.enqueueMessage(c.buildStatusEvent(stepID, statusSeq, runtimecontrolv1.RuntimeStepStatus_CANCELLED, stopReason, kernelInstanceID))
		c.enqueueMessage(c.buildStepResult(stepID, runtimecontrolv1.RuntimeStepStatus_CANCELLED, stopReason, runtimeMeta))
		return
	}

	detail := "saki-agent 当前分支尚未接入 Kernel 执行链路，任务按占位模式失败"
	runtimeMeta := map[string]any{
		"runtime_kind": c.cfg.RuntimeKind,
		"reason":       "not_implemented",
	}
	c.enqueueMessage(c.buildStatusEvent(stepID, statusSeq, runtimecontrolv1.RuntimeStepStatus_FAILED, detail, kernelInstanceID))
	c.enqueueMessage(c.buildStepResult(stepID, runtimecontrolv1.RuntimeStepStatus_FAILED, detail, runtimeMeta))
}

func (c *Client) resolveStubDuration(step *runtimecontrolv1.StepPayload) time.Duration {
	if step == nil {
		return defaultStubStepDuration
	}
	if raw := strings.TrimSpace(step.GetEnvOverrides()["SAKI_AGENT_STUB_DURATION_SEC"]); raw != "" {
		if parsed, ok := parsePositiveDuration(raw); ok {
			return parsed
		}
	}
	hints := step.GetRuntimeHints()
	if hints == nil {
		return defaultStubStepDuration
	}
	raw, ok := hints.AsMap()["stub_duration_sec"]
	if !ok {
		return defaultStubStepDuration
	}
	if parsed, ok := parsePositiveDuration(cast.ToString(raw)); ok {
		return parsed
	}
	return defaultStubStepDuration
}

func (c *Client) currentStepSnapshot() (bool, string) {
	c.stepMu.Lock()
	defer c.stepMu.Unlock()
	if c.runningStep == nil {
		return false, ""
	}
	return true, c.runningStep.stepID
}

func (c *Client) abortRunningStep() {
	c.stepMu.Lock()
	running := c.runningStep
	if running == nil {
		c.stepMu.Unlock()
		return
	}
	c.runningStep = nil
	cancel := running.cancel
	done := running.done
	c.stepMu.Unlock()

	if cancel != nil {
		cancel()
	}
	if done != nil {
		select {
		case <-done:
		case <-time.After(500 * time.Millisecond):
		}
	}
}

func (c *Client) nextSeqLocked(step *runningStep) int64 {
	step.seq++
	return step.seq
}

func (c *Client) enqueueMessage(message *runtimecontrolv1.RuntimeMessage) {
	if message == nil {
		return
	}
	select {
	case c.outgoingCh <- message:
	default:
		c.logger.Warn().Msg("runtime outgoing 队列已满，消息已丢弃")
	}
}

func (c *Client) drainOutgoingQueue() {
	for {
		select {
		case <-c.outgoingCh:
		default:
			return
		}
	}
}

func (c *Client) buildAck(
	ackFor string,
	status runtimecontrolv1.AckStatus,
	ackType runtimecontrolv1.AckType,
	reason runtimecontrolv1.AckReason,
	detail string,
) *runtimecontrolv1.RuntimeMessage {
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_Ack{
			Ack: &runtimecontrolv1.Ack{
				RequestId: uuid.NewString(),
				AckFor:    strings.TrimSpace(ackFor),
				Status:    status,
				Type:      ackType,
				Reason:    reason,
				Detail:    detail,
			},
		},
	}
}

func (c *Client) buildStatusEvent(
	stepID string,
	seq int64,
	status runtimecontrolv1.RuntimeStepStatus,
	reason string,
	kernelInstanceID string,
) *runtimecontrolv1.RuntimeMessage {
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_StepEvent{
			StepEvent: &runtimecontrolv1.StepEvent{
				RequestId:        uuid.NewString(),
				StepId:           strings.TrimSpace(stepID),
				Seq:              seq,
				Ts:               time.Now().UTC().UnixMilli(),
				EventPayload:     &runtimecontrolv1.StepEvent_StatusEvent{StatusEvent: &runtimecontrolv1.StatusEvent{Status: status, Reason: reason}},
				KernelState:      status.String(),
				KernelInstanceId: strings.TrimSpace(kernelInstanceID),
			},
		},
	}
}

func (c *Client) buildStepResult(
	stepID string,
	status runtimecontrolv1.RuntimeStepStatus,
	errorMessage string,
	runtimeMeta map[string]any,
) *runtimecontrolv1.RuntimeMessage {
	meta, err := structpb.NewStruct(runtimeMeta)
	if err != nil {
		meta = &structpb.Struct{Fields: map[string]*structpb.Value{}}
	}
	return &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_StepResult{
			StepResult: &runtimecontrolv1.StepResult{
				RequestId:    uuid.NewString(),
				StepId:       strings.TrimSpace(stepID),
				Status:       status,
				ErrorMessage: strings.TrimSpace(errorMessage),
				RuntimeMeta:  meta,
			},
		},
	}
}

func (c *Client) setState(state string) {
	c.mu.Lock()
	c.state = state
	c.mu.Unlock()
}

func (c *Client) recordFailure(err error, backoff time.Duration) {
	c.mu.Lock()
	c.consecutiveFailures++
	if err != nil {
		c.lastError = err.Error()
	}
	c.state = StateBackoff
	c.nextRetryAt = time.Now().UTC().Add(backoff)
	c.mu.Unlock()
}

func (c *Client) waitOrWake(ctx context.Context, duration time.Duration) bool {
	timer := time.NewTimer(duration)
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

func (c *Client) signalWake() {
	if c == nil {
		return
	}
	select {
	case c.wakeCh <- struct{}{}:
	default:
	}
}

func (c *Client) connState() string {
	c.mu.RLock()
	conn := c.conn
	c.mu.RUnlock()
	if conn == nil {
		return "DISCONNECTED"
	}
	state := conn.GetState()
	if state == connectivity.Ready {
		return "READY"
	}
	return state.String()
}

func withToken(ctx context.Context, token string) context.Context {
	token = strings.TrimSpace(token)
	if token == "" {
		return ctx
	}
	return metadata.AppendToOutgoingContext(ctx, "x-internal-token", token)
}

func defaultID(prefix string) string {
	hostname, err := os.Hostname()
	if err != nil {
		return prefix + "-" + uuid.NewString()
	}
	hostname = strings.TrimSpace(hostname)
	if hostname == "" {
		return prefix + "-" + uuid.NewString()
	}
	return hostname
}

func parsePositiveDuration(raw string) (time.Duration, bool) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0, false
	}
	if parsed, err := time.ParseDuration(raw); err == nil && parsed > 0 {
		return parsed, true
	}
	if parsed, err := time.ParseDuration(raw + "s"); err == nil && parsed > 0 {
		return parsed, true
	}
	return 0, false
}

func minDuration(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}

func clonePluginSpecs(items []pluginloader.PluginSpec) []pluginloader.PluginSpec {
	if len(items) == 0 {
		return nil
	}
	out := make([]pluginloader.PluginSpec, 0, len(items))
	for _, item := range items {
		out = append(out, pluginloader.PluginSpec{
			ID:                   item.ID,
			Version:              item.Version,
			DisplayName:          item.DisplayName,
			SupportedStepTypes:   append([]string(nil), item.SupportedStepTypes...),
			SupportedStrategies:  append([]string(nil), item.SupportedStrategies...),
			RequestConfigSchema:  cloneAnyMap(item.RequestConfigSchema),
			DefaultRequestConfig: cloneAnyMap(item.DefaultRequestConfig),
			SupportsAutoFallback: item.SupportsAutoFallback,
			SourcePath:           item.SourcePath,
		})
	}
	return out
}

func cloneAnyMap(input map[string]any) map[string]any {
	if len(input) == 0 {
		return map[string]any{}
	}
	out := make(map[string]any, len(input))
	for key, value := range input {
		out[key] = value
	}
	return out
}

func errorFromText(raw string) error {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	return errors.New(raw)
}

func resourceSummaryFromCapabilities(caps *device.DeviceCapabilities) *runtimecontrolv1.ResourceSummary {
	summary := &runtimecontrolv1.ResourceSummary{
		GpuCount:     0,
		GpuDeviceIds: nil,
		CpuWorkers:   1,
		MemoryMb:     0,
		Accelerators: []*runtimecontrolv1.AcceleratorCapability{},
	}
	if caps == nil {
		summary.Accelerators = append(summary.Accelerators, &runtimecontrolv1.AcceleratorCapability{
			Type:        runtimecontrolv1.AcceleratorType_CPU,
			Available:   true,
			DeviceCount: 1,
			DeviceIds:   []string{"cpu:0"},
		})
		return summary
	}
	if caps.CPU != nil && caps.CPU.LogicalCores > 0 {
		summary.CpuWorkers = int32(caps.CPU.LogicalCores)
	}
	summary.Accelerators = append(summary.Accelerators, &runtimecontrolv1.AcceleratorCapability{
		Type:        runtimecontrolv1.AcceleratorType_CPU,
		Available:   true,
		DeviceCount: 1,
		DeviceIds:   []string{"cpu:0"},
	})
	if caps.CUDA != nil {
		deviceIDs := make([]string, 0, caps.CUDA.DeviceCount)
		gpuIDs := make([]int32, 0, caps.CUDA.DeviceCount)
		for idx := 0; idx < caps.CUDA.DeviceCount; idx++ {
			deviceIDs = append(deviceIDs, fmt.Sprintf("cuda:%d", idx))
			gpuIDs = append(gpuIDs, int32(idx))
		}
		if caps.CUDA.Available {
			summary.GpuCount += int32(caps.CUDA.DeviceCount)
			summary.GpuDeviceIds = append(summary.GpuDeviceIds, gpuIDs...)
		}
		summary.Accelerators = append(summary.Accelerators, &runtimecontrolv1.AcceleratorCapability{
			Type:        runtimecontrolv1.AcceleratorType_CUDA,
			Available:   caps.CUDA.Available,
			DeviceCount: int32(caps.CUDA.DeviceCount),
			DeviceIds:   deviceIDs,
		})
	}
	if caps.MPS != nil {
		deviceCount := int32(0)
		deviceIDs := []string{}
		if caps.MPS.Available {
			deviceCount = 1
			deviceIDs = []string{"mps:0"}
			summary.GpuCount += 1
		}
		summary.Accelerators = append(summary.Accelerators, &runtimecontrolv1.AcceleratorCapability{
			Type:        runtimecontrolv1.AcceleratorType_MPS,
			Available:   caps.MPS.Available,
			DeviceCount: deviceCount,
			DeviceIds:   deviceIDs,
		})
	}
	return summary
}

func resourcesToSupportedAccelerators(resources *runtimecontrolv1.ResourceSummary) []runtimecontrolv1.AcceleratorType {
	if resources == nil {
		return []runtimecontrolv1.AcceleratorType{runtimecontrolv1.AcceleratorType_CPU}
	}
	types := make([]runtimecontrolv1.AcceleratorType, 0, len(resources.GetAccelerators()))
	for _, capability := range resources.GetAccelerators() {
		if capability.GetAvailable() {
			types = append(types, capability.GetType())
		}
	}
	if len(types) == 0 {
		types = append(types, runtimecontrolv1.AcceleratorType_CPU)
	}
	return types
}

func hardwareProfileMap(caps *device.DeviceCapabilities) map[string]any {
	if caps == nil {
		return map[string]any{
			"platform":    "unknown",
			"best_device": device.BestDeviceCPU,
		}
	}
	profile := map[string]any{
		"platform":    caps.Platform,
		"best_device": caps.BestDevice(),
	}
	if caps.CPU != nil {
		profile["cpu_model"] = caps.CPU.ModelName
		profile["cpu_arch"] = caps.CPU.Architecture
		profile["logical_cores"] = caps.CPU.LogicalCores
		profile["physical_cores"] = caps.CPU.PhysicalCores
	}
	if caps.CUDA != nil {
		profile["cuda_available"] = caps.CUDA.Available
		profile["cuda_device_count"] = caps.CUDA.DeviceCount
		profile["cuda_version"] = caps.CUDA.Version
	}
	if caps.MPS != nil {
		profile["mps_available"] = caps.MPS.Available
		profile["mps_version"] = caps.MPS.Version
	}
	return profile
}

func mpsStabilityProfileMap(caps *device.DeviceCapabilities) map[string]any {
	profile := map[string]any{
		"supports_mps_loss_cpu_fallback": false,
		"risk_level":                     "unknown",
	}
	if caps == nil || caps.MPS == nil || !caps.MPS.Available {
		return profile
	}
	profile["supports_mps_loss_cpu_fallback"] = true
	profile["risk_level"] = "guarded"
	return profile
}

func kernelCompatFlagsMap(caps *device.DeviceCapabilities) map[string]any {
	flags := map[string]any{
		"supports_mps_loss_cpu_fallback": false,
	}
	if caps == nil || caps.MPS == nil {
		return flags
	}
	flags["supports_mps_loss_cpu_fallback"] = caps.MPS.Available
	return flags
}
