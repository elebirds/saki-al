package main

import (
	"context"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"

	"github.com/elebirds/saki/saki-agent/internal/agent"
	"github.com/elebirds/saki/saki-agent/internal/config"
)

func main() {
	if err := run(); err != nil {
		log.Error().Err(err).Msg("saki-agent 异常退出")
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	setupLogger(cfg.LogLevel)
	logger := log.With().Str("component", "saki-agent").Logger()

	daemon, err := agent.New(agent.Config{
		RunDir:         cfg.RunDir,
		MinIOEndpoint:  cfg.MinIOEndpoint,
		MinIOAccessKey: cfg.MinIOAccessKey,
		MinIOSecretKey: cfg.MinIOSecretKey,
		MinIOBucket:    cfg.MinIOBucket,
		MinIOPrefix:    cfg.MinIOPrefix,
		MinIOUseSSL:    cfg.MinIOUseSSL,
	})
	if err != nil {
		return err
	}
	if err := daemon.PrepareRunDir(); err != nil {
		return err
	}
	if err := daemon.CleanupStaleSockets(); err != nil {
		return err
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	logger.Info().Msg("saki-agent 已启动")

	<-ctx.Done()
	logger.Info().Msg("收到退出信号，saki-agent 正在停机")
	return nil
}

func setupLogger(level string) {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})
	parsed, err := zerolog.ParseLevel(strings.ToLower(strings.TrimSpace(level)))
	if err != nil {
		parsed = zerolog.InfoLevel
	}
	zerolog.SetGlobalLevel(parsed)
}
