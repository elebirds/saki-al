package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/rs/zerolog/log"

	"github.com/elebirds/saki/saki-agent/internal/agent"
	"github.com/elebirds/saki/saki-agent/internal/config"
	"github.com/elebirds/saki/saki-agent/internal/runtimeclient"
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

	daemon, err := agent.NewWithLogger(agent.Config{
		RunDir:         cfg.RunDir,
		CacheDir:       cfg.CacheDir,
		MinIOEndpoint:  cfg.MinIOEndpoint,
		MinIOAccessKey: cfg.MinIOAccessKey,
		MinIOSecretKey: cfg.MinIOSecretKey,
		MinIOBucket:    cfg.MinIOBucket,
		MinIOPrefix:    cfg.MinIOPrefix,
		MinIOUseSSL:    cfg.MinIOUseSSL,
	}, logger.With().Str("service", "agent").Logger())
	if err != nil {
		return err
	}
	if err := daemon.PrepareRunDir(); err != nil {
		return err
	}
	if err := daemon.PrepareCacheDir(); err != nil {
		return err
	}
	if err := daemon.CleanupStaleSockets(); err != nil {
		return err
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	logger.Info().Msg("saki-agent 已启动")
	runtimeClient := runtimeclient.New(
		runtimeclient.Config{
			Target:            cfg.RuntimeControlTarget,
			Token:             cfg.InternalToken,
			ExecutorID:        cfg.ExecutorID,
			NodeID:            cfg.NodeID,
			Version:           cfg.Version,
			RuntimeKind:       cfg.RuntimeKind,
			KernelsDir:        cfg.KernelsDir,
			HeartbeatInterval: time.Duration(cfg.HeartbeatIntervalSec) * time.Second,
			ConnectTimeout:    time.Duration(cfg.ConnectTimeoutSec) * time.Second,
			InitialBackoff:    time.Duration(cfg.ReconnectInitialBackoffSec) * time.Second,
			MaxBackoff:        time.Duration(cfg.ReconnectMaxBackoffSec) * time.Second,
		},
		daemon,
		logger.With().Str("service", "runtime_client").Logger(),
	)
	runtimeClient.Start(ctx)
	defer func() {
		if err := runtimeClient.Close(); err != nil {
			logger.Warn().Err(err).Msg("关闭 runtime client 失败")
		}
	}()

	if cfg.EnableStdinCommands {
		startStdinCommandLoop(
			ctx,
			cancel,
			daemon,
			runtimeClient,
			logger.With().Str("module", "stdin_cmd").Logger(),
		)
	} else {
		logger.Info().Msg("stdin 命令台未启用")
	}

	<-ctx.Done()
	logger.Info().Msg("收到退出信号，saki-agent 正在停机")
	return nil
}
