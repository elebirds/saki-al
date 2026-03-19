package bootstrap

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"
)

const defaultReadHeaderTimeout = 5 * time.Second

type RuntimeClient interface {
	Register(ctx context.Context, capabilities []string) error
	Heartbeat(ctx context.Context, runningTaskIDs []string) error
}

type RunningTaskSource interface {
	RunningTaskIDs() []string
}

type Dependencies struct {
	Bind              string
	RuntimeClient     RuntimeClient
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
