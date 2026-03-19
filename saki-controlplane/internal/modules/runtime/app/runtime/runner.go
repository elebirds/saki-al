package runtime

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerecovery "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/recovery"
	runtimescheduler "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/scheduler"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/internalrpc"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"
)

const (
	defaultReadHeaderTimeout    = 5 * time.Second
	defaultSchedulerInterval    = 2 * time.Second
	defaultOutboxInterval       = 1 * time.Second
	defaultRecoveryInterval     = 5 * time.Second
	defaultAssignAckTimeout     = 30 * time.Second
	defaultHeartbeatTimeout     = 30 * time.Second
	defaultSchedulerLeaseName   = "runtime-scheduler"
	defaultSchedulerLeaseTTL    = 30 * time.Second
	defaultArtifactTicketExpiry = 15 * time.Minute
	healthzPath                 = "/healthz"
	healthzResponse             = "ok"
)

var errRuntimeArtifactProviderRequired = errors.New("runtime artifact provider is required")

type Options struct {
	Bind                          string
	Roles                         RoleSet
	DatabaseDSN                   string
	ReadHeaderTimeout             time.Duration
	SchedulerInterval             time.Duration
	OutboxInterval                time.Duration
	SchedulerLeaseName            string
	SchedulerHolder               string
	SchedulerLeaseTTL             time.Duration
	RecoveryAssignAckTimeout      time.Duration
	RecoveryAgentHeartbeatTimeout time.Duration
	AssetStoreFactory             func(pool *pgxpool.Pool) assetapp.Store
	AssetProvider                 storage.Provider
	UploadTicketExpiry            time.Duration
	DownloadTicketExpiry          time.Duration
}

type Runner struct {
	process *Process
}

type loopRunner interface {
	Run(ctx context.Context) error
}

type schedulerTicker interface {
	Tick(ctx context.Context) error
}

type outboxWorker interface {
	RunOnce(ctx context.Context) error
}

type recoveryLoopWorker interface {
	RunOnce(ctx context.Context) error
}

type deliveryCommandStore interface {
	ClaimForPush(ctx context.Context, limit int32, claimUntil time.Time) ([]runtimerepo.AgentCommand, error)
	Ack(ctx context.Context, commandID, claimToken uuid.UUID, ackAt time.Time) error
	MarkFinished(ctx context.Context, commandID, claimToken uuid.UUID, finishedAt time.Time) error
	MarkRetry(ctx context.Context, commandID, claimToken uuid.UUID, nextAvailableAt time.Time, lastError string) error
}

type deliveryAgentStore interface {
	GetByID(ctx context.Context, agentID string) (*runtimerepo.Agent, error)
}

type deliverySessionStore interface {
	GetByAgentID(ctx context.Context, agentID string) (*runtimerepo.AgentSession, error)
}

type rpcHandlerMount struct {
	path    string
	handler http.Handler
}

type assembly struct {
	bind              string
	roles             RoleSet
	readHeaderTimeout time.Duration
	rpcHandlers       []rpcHandlerMount
	schedulerTicker   schedulerTicker
	outboxWorker      outboxWorker
	recoveryWorker    recoveryLoopWorker
	schedulerInterval time.Duration
	outboxInterval    time.Duration
	logger            *slog.Logger
}

func New(ctx context.Context, opts Options, logger *slog.Logger) (*Runner, error) {
	cfg := withDefaultOptions(opts)
	log := loggerOrDefault(logger)
	if cfg.AssetProvider == nil {
		return nil, errRuntimeArtifactProviderRequired
	}
	if err := probeArtifactProvider(ctx, cfg.AssetProvider); err != nil {
		return nil, fmt.Errorf("runtime artifact storage probe failed: %w", err)
	}

	pool, err := appdb.NewPool(ctx, cfg.DatabaseDSN)
	if err != nil {
		return nil, err
	}

	leaseRepo := runtimerepo.NewLeaseRepo(pool)
	taskRepo := runtimerepo.NewTaskRepo(pool)
	commandRepo := runtimerepo.NewAgentCommandRepo(pool)
	agentRepo := runtimerepo.NewAgentRepo(pool)
	sessionRepo := runtimerepo.NewAgentSessionRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)
	assetStore := cfg.assetStoreFactory()(pool)
	if assetStore == nil {
		pool.Close()
		return nil, errors.New("runtime artifact store factory returned nil")
	}

	ingressServer := internalrpc.NewRuntimeServer(
		runtimecommands.NewRegisterAgentHandler(agentRepo),
		runtimecommands.NewHeartbeatAgentHandler(agentRepo),
		runtimecommands.NewStartTaskHandler(taskRepo),
		runtimecommands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		runtimecommands.NewFailTaskHandler(taskRepo),
		runtimecommands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	deliveryServer := internalrpc.NewDeliveryServer(commandRepo)
	deliveryPath, deliveryHandler := runtimev1connect.NewAgentDeliveryHandler(deliveryServer)
	relayBaseURL := relayBaseURLFromBind(cfg.Bind)
	relayServer := internalrpc.NewRelayServer(relayBaseURL, sessionRepo)
	relayPath, relayHandler := runtimev1connect.NewAgentRelayHandler(relayServer)
	artifactServer := internalrpc.NewArtifactServer(
		assetapp.NewIssueUploadTicketUseCase(assetStore, cfg.AssetProvider, cfg.UploadTicketExpiry),
		assetapp.NewIssueDownloadTicketUseCase(assetStore, cfg.AssetProvider, cfg.DownloadTicketExpiry),
	)
	artifactPath, artifactHandler := runtimev1connect.NewArtifactServiceHandler(artifactServer)

	assigner := runtimecommands.NewAssignTaskHandlerWithTx(
		runtimerepo.NewAssignTaskTxRunner(pool),
		runtimescheduler.NewAgentSelector(),
	)
	ticker := newSchedulerTicker(cfg, leaseRepo, assigner, log)

	worker := newDeliveryWorker(relayBaseURL, commandRepo, agentRepo, sessionRepo, nil)
	recoveryWorker := runtimerecovery.NewWorker(
		newRuntimeRecoveryStore(taskRepo, agentRepo),
		runtimerecovery.Policy{
			AssignAckTimeout:      cfg.RecoveryAssignAckTimeout,
			AgentHeartbeatTimeout: cfg.RecoveryAgentHeartbeatTimeout,
		},
	)

	runner := newRunnerFromAssembly(assembly{
		bind:              cfg.Bind,
		roles:             cfg.Roles,
		readHeaderTimeout: cfg.ReadHeaderTimeout,
		rpcHandlers: []rpcHandlerMount{
			{
				path:    ingressPath,
				handler: ingressHandler,
			},
			{
				path:    deliveryPath,
				handler: deliveryHandler,
			},
			{
				path:    relayPath,
				handler: relayHandler,
			},
			{
				path:    artifactPath,
				handler: artifactHandler,
			},
		},
		schedulerTicker:   ticker,
		outboxWorker:      worker,
		recoveryWorker:    recoveryWorker,
		schedulerInterval: cfg.SchedulerInterval,
		outboxInterval:    cfg.OutboxInterval,
		logger:            log,
	})
	runner.Server().RegisterOnShutdown(func() {
		pool.Close()
	})

	return runner, nil
}

func (r *Runner) Server() *http.Server {
	if r == nil || r.process == nil {
		return nil
	}
	return r.process.Server()
}

func (r *Runner) Run(ctx context.Context) error {
	if r == nil || r.process == nil {
		return nil
	}
	return r.process.Run(ctx)
}

func probeArtifactProvider(ctx context.Context, provider storage.Provider) error {
	if provider == nil {
		return errRuntimeArtifactProviderRequired
	}

	probeKey := fmt.Sprintf("runtime/probe/%d", time.Now().UnixNano())
	_, err := provider.StatObject(ctx, probeKey)
	if err == nil || errors.Is(err, storage.ErrObjectNotFound) {
		return nil
	}
	return err
}

func newRunnerFromAssembly(parts assembly) *Runner {
	log := loggerOrDefault(parts.logger)
	mux := http.NewServeMux()
	mux.HandleFunc(healthzPath, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(healthzResponse))
	})
	for _, mount := range ingressRoleHandlers(parts.roles, parts.rpcHandlers) {
		if mount.path == "" || mount.handler == nil {
			continue
		}
		mux.Handle(mount.path, mount.handler)
	}

	return &Runner{
		process: newProcess(
			&http.Server{
				Addr:              parts.bind,
				Handler:           h2c.NewHandler(mux, &http2.Server{}),
				ReadHeaderTimeout: durationOrDefault(parts.readHeaderTimeout, defaultReadHeaderTimeout),
			},
			schedulerRoleLoop(parts, log),
			deliveryRoleLoop(parts, log),
			recoveryRoleLoop(parts, log),
		),
	}
}

func newSchedulerTicker(
	cfg Options,
	leases runtimescheduler.LeaseManager,
	assigner runtimescheduler.DispatchTaskAssigner,
	logger *slog.Logger,
) schedulerTicker {
	_ = loggerOrDefault(logger)
	dispatch := runtimescheduler.NewDispatchScan(assigner)
	return runtimescheduler.NewLeaderTicker(
		leases,
		dispatch,
		cfg.SchedulerLeaseName,
		cfg.SchedulerHolder,
		cfg.SchedulerLeaseTTL,
	)
}

type pollingLoopConfig struct {
	name     string
	interval time.Duration
	runOnce  func(ctx context.Context) error
	logger   *slog.Logger
}

type pollingLoop struct {
	name     string
	interval time.Duration
	runOnce  func(ctx context.Context) error
	logger   *slog.Logger
}

func newPollingLoop(cfg pollingLoopConfig) *pollingLoop {
	return &pollingLoop{
		name:     cfg.name,
		interval: cfg.interval,
		runOnce:  cfg.runOnce,
		logger:   loggerOrDefault(cfg.logger),
	}
}

func (l *pollingLoop) Run(ctx context.Context) error {
	if err := l.runOnce(ctx); err != nil && ctx.Err() == nil {
		l.logger.Error("runtime loop tick failed", "loop", l.name, "err", err)
	}

	ticker := time.NewTicker(l.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if err := l.runOnce(ctx); err != nil && ctx.Err() == nil {
				l.logger.Error("runtime loop tick failed", "loop", l.name, "err", err)
			}
		}
	}
}

type noopSchedulerTickerImpl struct{}

func (noopSchedulerTickerImpl) Tick(context.Context) error {
	return nil
}

func schedulerTickFunc(ticker schedulerTicker) func(context.Context) error {
	if ticker == nil {
		ticker = noopSchedulerTickerImpl{}
	}
	return ticker.Tick
}

type noopOutboxWorkerImpl struct{}

func (noopOutboxWorkerImpl) RunOnce(context.Context) error {
	return nil
}

func outboxRunOnceFunc(worker outboxWorker) func(context.Context) error {
	if worker == nil {
		worker = noopOutboxWorkerImpl{}
	}
	return worker.RunOnce
}

func withDefaultOptions(opts Options) Options {
	if opts.ReadHeaderTimeout <= 0 {
		opts.ReadHeaderTimeout = defaultReadHeaderTimeout
	}
	if opts.SchedulerInterval <= 0 {
		opts.SchedulerInterval = defaultSchedulerInterval
	}
	if opts.OutboxInterval <= 0 {
		opts.OutboxInterval = defaultOutboxInterval
	}
	if opts.RecoveryAssignAckTimeout <= 0 {
		opts.RecoveryAssignAckTimeout = defaultAssignAckTimeout
	}
	if opts.RecoveryAgentHeartbeatTimeout <= 0 {
		opts.RecoveryAgentHeartbeatTimeout = defaultHeartbeatTimeout
	}
	if opts.SchedulerLeaseName == "" {
		opts.SchedulerLeaseName = defaultSchedulerLeaseName
	}
	if opts.SchedulerHolder == "" {
		opts.SchedulerHolder = defaultSchedulerHolder()
	}
	if opts.SchedulerLeaseTTL <= 0 {
		opts.SchedulerLeaseTTL = defaultSchedulerLeaseTTL
	}
	if opts.UploadTicketExpiry <= 0 {
		opts.UploadTicketExpiry = defaultArtifactTicketExpiry
	}
	if opts.DownloadTicketExpiry <= 0 {
		opts.DownloadTicketExpiry = defaultArtifactTicketExpiry
	}
	if len(opts.Roles) == 0 {
		opts.Roles = DefaultRoleSet()
	}
	return opts
}

func (o Options) assetStoreFactory() func(pool *pgxpool.Pool) assetapp.Store {
	if o.AssetStoreFactory != nil {
		return o.AssetStoreFactory
	}
	return func(pool *pgxpool.Pool) assetapp.Store {
		return assetapp.NewRepoStore(assetrepo.NewAssetRepo(pool))
	}
}

func defaultSchedulerHolder() string {
	host, err := os.Hostname()
	if err != nil || host == "" {
		host = "runtime"
	}
	return fmt.Sprintf("%s-%d", host, os.Getpid())
}

func loggerOrDefault(logger *slog.Logger) *slog.Logger {
	if logger != nil {
		return logger
	}
	return slog.Default()
}

func durationOrDefault(value, fallback time.Duration) time.Duration {
	if value <= 0 {
		return fallback
	}
	return value
}

func newDeliveryWorker(relayBaseURL string, commandStore deliveryCommandStore, agentStore deliveryAgentStore, sessionStore deliverySessionStore, httpClient *http.Client) *runtimeeffects.Worker {
	// delivery 只消费 agent_command 真相；全局 AgentControlBaseURL 已退出主路径。
	// direct 按 agent.control_base_url 推送，pull 保持 pending 由 agent 自己领取，relay 只把命令交给在线 session。
	transports := runtimeeffects.NewTransportRegistry(
		runtimeeffects.NewDirectTransport(agentStore, newAgentControlClientFactory(httpClient)),
		runtimeeffects.NewPullTransport(),
		runtimeeffects.NewRelayTransport(sessionStore, runtimeeffects.NewConnectRelayDispatchClientFactory(httpClient), relayBaseURL),
	)
	return runtimeeffects.NewWorker(
		commandStore,
		runtimeeffects.NewDispatchEffect(transports),
		runtimeeffects.NewStopEffect(transports),
	)
}

func relayBaseURLFromBind(bind string) string {
	host, port, err := net.SplitHostPort(bind)
	if err != nil {
		return ""
	}
	switch host {
	case "", "0.0.0.0", "::":
		host = "127.0.0.1"
	}
	return "http://" + net.JoinHostPort(host, port)
}
