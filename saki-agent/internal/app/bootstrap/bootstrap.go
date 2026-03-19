package bootstrap

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
)

const (
	defaultReadHeaderTimeout = 5 * time.Second
	defaultPullBatchSize     = int32(8)
	defaultPullWaitTimeout   = 25 * time.Second
	defaultPullRetryBackoff  = time.Second
)

type RuntimeClient interface {
	Register(ctx context.Context, capabilities []string) error
	Heartbeat(ctx context.Context, runningTaskIDs []string) error
}

type RunningTaskSource interface {
	RunningTaskIDs() []string
}

type DeliveryClient interface {
	PullCommands(ctx context.Context, maxItems int32, waitTimeout time.Duration) ([]*runtimev1.PulledCommand, error)
	AckReceived(ctx context.Context, commandID string, deliveryToken string) error
}

type PulledCommandHandler interface {
	HandlePulledCommand(ctx context.Context, cmd *runtimev1.PulledCommand) error
}

type Dependencies struct {
	Bind              string
	RuntimeClient     RuntimeClient
	DeliveryClient    DeliveryClient
	CommandHandler    PulledCommandHandler
	TaskSource        RunningTaskSource
	Capabilities      []string
	HeartbeatInterval time.Duration
	ControlPath       string
	ControlHandler    http.Handler
	Logger            *slog.Logger
}

type Runner struct {
	server            *http.Server
	runtimeClient     RuntimeClient
	deliveryClient    DeliveryClient
	commandHandler    PulledCommandHandler
	taskSource        RunningTaskSource
	capabilities      []string
	heartbeatInterval time.Duration
	logger            *slog.Logger
}

func New(deps Dependencies) *Runner {
	logger := deps.Logger
	if logger == nil {
		logger = slog.Default()
	}
	heartbeatInterval := deps.HeartbeatInterval
	if heartbeatInterval <= 0 {
		heartbeatInterval = 30 * time.Second
	}

	mux := http.NewServeMux()
	if deps.ControlPath != "" && deps.ControlHandler != nil {
		mux.Handle(deps.ControlPath, deps.ControlHandler)
	}
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	bind := deps.Bind
	if bind == "" {
		bind = ":18081"
	}

	return &Runner{
		server: &http.Server{
			Addr:              bind,
			Handler:           mux,
			ReadHeaderTimeout: defaultReadHeaderTimeout,
		},
		runtimeClient:     deps.RuntimeClient,
		deliveryClient:    deps.DeliveryClient,
		commandHandler:    deps.CommandHandler,
		taskSource:        deps.TaskSource,
		capabilities:      append([]string(nil), deps.Capabilities...),
		heartbeatInterval: heartbeatInterval,
		logger:            logger,
	}
}

func (r *Runner) Server() *http.Server {
	return r.server
}

func (r *Runner) StartBackground(ctx context.Context) error {
	if r.runtimeClient == nil {
		<-ctx.Done()
		return nil
	}

	if err := r.runtimeClient.Register(ctx, append([]string(nil), r.capabilities...)); err != nil {
		return err
	}
	if err := r.runtimeClient.Heartbeat(ctx, r.runningTaskIDs()); err != nil {
		return err
	}

	errCh := make(chan error, 2)
	go func() {
		errCh <- r.runHeartbeatLoop(ctx)
	}()
	if r.deliveryClient != nil && r.commandHandler != nil {
		go func() {
			errCh <- r.runPullLoop(ctx)
		}()
	}

	for {
		select {
		case <-ctx.Done():
			return nil
		case err := <-errCh:
			if err == nil {
				if ctx.Err() != nil {
					return nil
				}
				continue
			}
			if errors.Is(ctx.Err(), context.Canceled) {
				return nil
			}
			return err
		}
	}
}

func (r *Runner) runHeartbeatLoop(ctx context.Context) error {
	ticker := time.NewTicker(r.heartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if err := r.runtimeClient.Heartbeat(ctx, r.runningTaskIDs()); err != nil {
				if errors.Is(ctx.Err(), context.Canceled) {
					return nil
				}
				return err
			}
		}
	}
}

func (r *Runner) runPullLoop(ctx context.Context) error {
	for {
		if ctx.Err() != nil {
			return nil
		}

		commands, err := r.deliveryClient.PullCommands(ctx, defaultPullBatchSize, defaultPullWaitTimeout)
		if err != nil {
			if errors.Is(ctx.Err(), context.Canceled) {
				return nil
			}
			r.logger.Error("agent pull commands failed", "err", err)
			if err := waitForBackoff(ctx, defaultPullRetryBackoff); err != nil {
				return nil
			}
			continue
		}

		for _, command := range commands {
			if command == nil {
				continue
			}
			// pull 命令先交给本地 runtime 完成 admission/stop handoff；
			// handoff 成功后再 ack(received)，这样失败命令会在 claim 过期后重试，而不会被误确认。
			if err := r.commandHandler.HandlePulledCommand(ctx, command); err != nil {
				r.logger.Error("agent handle pulled command failed", "command_id", command.GetCommandId(), "command_type", command.GetCommandType(), "err", err)
				continue
			}
			if err := r.deliveryClient.AckReceived(ctx, command.GetCommandId(), command.GetDeliveryToken()); err != nil {
				if errors.Is(ctx.Err(), context.Canceled) {
					return nil
				}
				r.logger.Error("agent ack pulled command failed", "command_id", command.GetCommandId(), "err", err)
			}
		}
	}
}

func (r *Runner) Run(ctx context.Context) error {
	backgroundDone := make(chan error, 1)
	serverDone := make(chan error, 1)

	go func() {
		backgroundDone <- r.StartBackground(ctx)
	}()
	go func() {
		err := r.server.ListenAndServe()
		if errors.Is(err, http.ErrServerClosed) {
			serverDone <- nil
			return
		}
		serverDone <- err
	}()

	select {
	case err := <-backgroundDone:
		if err != nil {
			_ = r.server.Shutdown(context.Background())
			return err
		}
	case err := <-serverDone:
		if err != nil {
			return err
		}
	case <-ctx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := r.server.Shutdown(shutdownCtx); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return <-backgroundDone
}

func (r *Runner) runningTaskIDs() []string {
	if r.taskSource == nil {
		return nil
	}
	return r.taskSource.RunningTaskIDs()
}

func waitForBackoff(ctx context.Context, backoff time.Duration) error {
	timer := time.NewTimer(backoff)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
