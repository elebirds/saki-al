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
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		slog.Error("load agent config failed", "err", err)
		os.Exit(1)
	}

	runtimeClient := appconnect.NewRuntimeClient(http.DefaultClient, cfg.RuntimeBaseURL, cfg.AgentID, cfg.AgentVersion, slog.Default())
	runner := bootstrap.New(bootstrap.Dependencies{
		Bind:              cfg.AgentControlBind,
		RuntimeClient:     runtimeClient,
		HeartbeatInterval: cfg.AgentHeartbeatInterval,
	})

	if err := runner.Run(ctx); err != nil {
		slog.Error("agent exited", "err", err)
		os.Exit(1)
	}
}
