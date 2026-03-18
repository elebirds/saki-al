package runtime

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	runtimecommands "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimescheduler "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/scheduler"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/internalrpc"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/sync/errgroup"
)

const (
	defaultReadHeaderTimeout     = 5 * time.Second
	defaultSchedulerInterval     = 2 * time.Second
	defaultOutboxInterval        = 1 * time.Second
	defaultShutdownTimeout       = 5 * time.Second
	defaultSchedulerLeaseName    = "runtime-scheduler"
	defaultSchedulerLeaseTTL     = 30 * time.Second
	defaultArtifactTicketExpiry  = 15 * time.Minute
	healthzPath                  = "/healthz"
	healthzResponse              = "ok"
	placeholderTransportLogLabel = "runtime agent control placeholder is active"
)

var errPlaceholderAgentControlTransport = errors.New("runtime agent control transport is not configured")
var errRuntimeArtifactProviderRequired = errors.New("runtime artifact provider is required")

type Options struct {
	Bind                 string
	DatabaseDSN          string
	ReadHeaderTimeout    time.Duration
	SchedulerInterval    time.Duration
	OutboxInterval       time.Duration
	SchedulerLeaseName   string
	SchedulerHolder      string
	SchedulerLeaseTTL    time.Duration
	SchedulerTargetAgent string
	AssetStoreFactory    func(pool *pgxpool.Pool) assetapp.Store
	AssetProvider        storage.Provider
	UploadTicketExpiry   time.Duration
	DownloadTicketExpiry time.Duration
}

type Runner struct {
	server        *http.Server
	schedulerLoop loopRunner
	outboxLoop    loopRunner
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

type rpcHandlerMount struct {
	path    string
	handler http.Handler
}

type assembly struct {
	bind              string
	readHeaderTimeout time.Duration
	rpcHandlers       []rpcHandlerMount
	schedulerTicker   schedulerTicker
	outboxWorker      outboxWorker
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
	outboxRepo := runtimerepo.NewOutboxRepo(pool)
	executorRepo := runtimerepo.NewExecutorRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)
	assetStore := cfg.assetStoreFactory()(pool)
	if assetStore == nil {
		pool.Close()
		return nil, errors.New("runtime artifact store factory returned nil")
	}

	ingressServer := internalrpc.NewRuntimeServer(
		runtimecommands.NewRegisterExecutorHandler(executorRepo),
		runtimecommands.NewHeartbeatExecutorHandler(executorRepo),
		runtimecommands.NewStartTaskHandler(taskRepo),
		runtimecommands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		runtimecommands.NewFailTaskHandler(taskRepo),
		runtimecommands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	artifactServer := internalrpc.NewArtifactServer(
		assetapp.NewIssueUploadTicketUseCase(assetStore, cfg.AssetProvider, cfg.UploadTicketExpiry),
		assetapp.NewIssueDownloadTicketUseCase(assetStore, cfg.AssetProvider, cfg.DownloadTicketExpiry),
	)
	artifactPath, artifactHandler := runtimev1connect.NewArtifactServiceHandler(artifactServer)

	assigner := runtimecommands.NewAssignTaskHandlerWithTx(runtimerepo.NewAssignTaskTxRunner(pool))
	ticker := newSchedulerTicker(cfg, leaseRepo, assigner, log)

	controlClient := &placeholderAgentControlClient{logger: log}
	worker := runtimeeffects.NewWorker(
		outboxRepo,
		runtimeeffects.NewDispatchEffect(controlClient),
		runtimeeffects.NewStopEffect(controlClient),
	)

	runner := newRunnerFromAssembly(assembly{
		bind:              cfg.Bind,
		readHeaderTimeout: cfg.ReadHeaderTimeout,
		rpcHandlers: []rpcHandlerMount{
			{
				path:    ingressPath,
				handler: ingressHandler,
			},
			{
				path:    artifactPath,
				handler: artifactHandler,
			},
		},
		schedulerTicker:   ticker,
		outboxWorker:      worker,
		schedulerInterval: cfg.SchedulerInterval,
		outboxInterval:    cfg.OutboxInterval,
		logger:            log,
	})
	runner.server.RegisterOnShutdown(func() {
		pool.Close()
	})

	return runner, nil
}

func (r *Runner) Server() *http.Server {
	return r.server
}

func (r *Runner) Run(ctx context.Context) error {
	group, runCtx := errgroup.WithContext(ctx)
	group.Go(func() error {
		return r.schedulerLoop.Run(runCtx)
	})
	group.Go(func() error {
		return r.outboxLoop.Run(runCtx)
	})
	group.Go(func() error {
		err := r.server.ListenAndServe()
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	})
	group.Go(func() error {
		<-runCtx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), defaultShutdownTimeout)
		defer cancel()
		err := r.server.Shutdown(shutdownCtx)
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	})

	return group.Wait()
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
	for _, mount := range parts.rpcHandlers {
		if mount.path == "" || mount.handler == nil {
			continue
		}
		mux.Handle(mount.path, mount.handler)
	}

	return &Runner{
		server: &http.Server{
			Addr:              parts.bind,
			Handler:           mux,
			ReadHeaderTimeout: durationOrDefault(parts.readHeaderTimeout, defaultReadHeaderTimeout),
		},
		schedulerLoop: newPollingLoop(pollingLoopConfig{
			name:     "scheduler",
			interval: durationOrDefault(parts.schedulerInterval, defaultSchedulerInterval),
			runOnce:  schedulerTickFunc(parts.schedulerTicker),
			logger:   log,
		}),
		outboxLoop: newPollingLoop(pollingLoopConfig{
			name:     "outbox-worker",
			interval: durationOrDefault(parts.outboxInterval, defaultOutboxInterval),
			runOnce:  outboxRunOnceFunc(parts.outboxWorker),
			logger:   log,
		}),
	}
}

func newSchedulerTicker(
	cfg Options,
	leases runtimescheduler.LeaseManager,
	assigner runtimescheduler.DispatchTaskAssigner,
	logger *slog.Logger,
) schedulerTicker {
	log := loggerOrDefault(logger)
	if cfg.SchedulerTargetAgent == "" {
		log.Warn("runtime scheduler is disabled until a target agent is configured")
		return noopSchedulerTickerImpl{}
	}

	dispatch := runtimescheduler.NewDispatchScan(assigner, cfg.SchedulerTargetAgent)
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

type placeholderAgentControlClient struct {
	logger *slog.Logger
}

func (c *placeholderAgentControlClient) AssignTask(_ context.Context, req *runtimev1.AssignTaskRequest) error {
	c.logger.Warn(placeholderTransportLogLabel,
		"method", "AssignTask",
		"task_id", req.GetTaskId(),
		"execution_id", req.GetExecutionId(),
	)
	return errPlaceholderAgentControlTransport
}

func (c *placeholderAgentControlClient) StopTask(_ context.Context, req *runtimev1.StopTaskRequest) error {
	c.logger.Warn(placeholderTransportLogLabel,
		"method", "StopTask",
		"task_id", req.GetTaskId(),
		"execution_id", req.GetExecutionId(),
	)
	return errPlaceholderAgentControlTransport
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
