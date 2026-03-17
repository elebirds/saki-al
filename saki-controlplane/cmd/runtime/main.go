package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	runner, logger, err := bootstrap.NewRuntime(ctx)
	if err != nil {
		slog.New(slog.NewTextHandler(os.Stderr, nil)).Error("bootstrap runtime failed", "err", err)
		os.Exit(1)
	}

	logger.Info("starting runtime", "addr", runner.Server().Addr)
	if err := runner.Run(ctx); err != nil {
		logger.Error("runtime exited", "err", err)
		os.Exit(1)
	}
}
