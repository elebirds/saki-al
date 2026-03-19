package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/elebirds/saki/saki-agent/internal/app/bootstrap"
	"github.com/elebirds/saki/saki-agent/internal/app/config"
	appconnect "github.com/elebirds/saki/saki-agent/internal/app/connect"
	appruntime "github.com/elebirds/saki/saki-agent/internal/app/runtime"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-agent/internal/plugins/launcher"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		slog.Error("load agent config failed", "err", err)
		os.Exit(1)
	}

	runner := newRunner(cfg, slog.Default())

	if err := runner.Run(ctx); err != nil {
		slog.Error("agent exited", "err", err)
		os.Exit(1)
	}
}

func newRunner(cfg config.Config, logger *slog.Logger) *bootstrap.Runner {
	if logger == nil {
		logger = slog.Default()
	}

	runtimeClient := appconnect.NewRuntimeClient(http.DefaultClient, cfg.RuntimeBaseURL, cfg.AgentID, cfg.AgentVersion, logger)
	workerLauncher := launcher.NewLauncher(launcher.LauncherConfig{
		Command: append([]string(nil), cfg.AgentWorkerCommand...),
	})
	service := appruntime.NewService(cfg.AgentID, workerLauncher, runtimeClient)
	controlServer := appruntime.NewControlServer(service)
	controlPath, controlHandler := runtimev1connect.NewAgentControlHandler(controlServer)

	return bootstrap.New(bootstrap.Dependencies{
		Bind:              cfg.AgentControlBind,
		RuntimeClient:     runtimeClient,
		TaskSource:        service,
		HeartbeatInterval: cfg.AgentHeartbeatInterval,
		ControlPath:       controlPath,
		ControlHandler:    controlHandler,
		Logger:            logger,
	})
}
