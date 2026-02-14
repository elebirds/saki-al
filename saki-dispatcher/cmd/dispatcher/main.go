package main

import (
	"context"
	"fmt"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"

	grpc_recovery "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/recovery"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	"github.com/elebirds/saki/saki-dispatcher/internal/config"
	"github.com/elebirds/saki/saki-dispatcher/internal/controlplane"
	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	dispatcheradminv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/dispatcheradminv1"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	"github.com/elebirds/saki/saki-dispatcher/internal/orchestrator"
	"github.com/elebirds/saki/saki-dispatcher/internal/repo"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
	"github.com/elebirds/saki/saki-dispatcher/internal/server/admingrpc"
	"github.com/elebirds/saki/saki-dispatcher/internal/server/runtimegrpc"
)

func main() {
	if err := run(); err != nil {
		log.Error().Err(err).Msg("dispatcher exited with error")
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	setupLogger(cfg.LogLevel)
	logger := log.With().Str("component", "saki-dispatcher").Logger()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	repository, err := repo.NewRuntimeRepo(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	if repository != nil {
		defer repository.Close()
		logger.Info().Msg("database connection ready")
	} else {
		logger.Warn().Msg("DATABASE_URL is empty: runtime persistence is not enabled yet")
	}

	domainClient := runtime_domain_client.New(cfg.RuntimeDomainTarget, cfg.RuntimeDomainToken, 5)
	if domainClient.Enabled() {
		logger.Info().Str("target", cfg.RuntimeDomainTarget).Msg("connecting runtime_domain")
		if err := domainClient.Connect(ctx); err != nil {
			return err
		}
		logger.Info().Str("target", cfg.RuntimeDomainTarget).Msg("runtime_domain connected")
	} else {
		logger.Warn().Msg("RUNTIME_DOMAIN_TARGET is empty: runtime_domain bridge is disabled")
	}
	defer func() {
		if err := domainClient.Close(); err != nil {
			logger.Warn().Err(err).Str("target", cfg.RuntimeDomainTarget).Msg("runtime_domain disconnect failed")
			return
		}
		if domainClient.Enabled() {
			logger.Info().Str("target", cfg.RuntimeDomainTarget).Msg("runtime_domain disconnected")
		}
	}()

	dispatcher := dispatch.NewDispatcher()
	controlPlane := controlplane.NewService(
		repository,
		dispatcher,
		domainClient,
		cfg.DispatchScanLockKey,
		logger.With().Str("service", "controlplane").Logger(),
	)
	runtimeServer := runtimegrpc.NewServer(
		dispatcher,
		controlPlane,
		domainClient,
		logger.With().Str("grpc", "runtime").Logger(),
	)
	adminServer := admingrpc.NewServer(dispatcher, controlPlane, logger.With().Str("grpc", "admin").Logger())

	runtimeLis, err := net.Listen("tcp", cfg.RuntimeGRPCBind)
	if err != nil {
		return fmt.Errorf("listen runtime grpc: %w", err)
	}
	adminLis, err := net.Listen("tcp", cfg.AdminGRPCBind)
	if err != nil {
		return fmt.Errorf("listen admin grpc: %w", err)
	}

	runtimeGRPC := grpc.NewServer(
		grpc.ChainStreamInterceptor(
			grpc_recovery.StreamServerInterceptor(),
			streamAuthInterceptor(cfg.InternalToken),
		),
	)
	adminGRPC := grpc.NewServer(
		grpc.ChainUnaryInterceptor(
			grpc_recovery.UnaryServerInterceptor(),
			unaryAuthInterceptor(cfg.InternalToken),
		),
		grpc.ChainStreamInterceptor(
			grpc_recovery.StreamServerInterceptor(),
			streamAuthInterceptor(cfg.InternalToken),
		),
	)

	runtimecontrolv1.RegisterRuntimeControlServer(runtimeGRPC, runtimeServer)
	dispatcheradminv1.RegisterDispatcherAdminServer(adminGRPC, adminServer)

	orch := orchestrator.NewService(
		cfg.DispatchIntervalSec,
		controlPlane,
		logger.With().Str("service", "orchestrator").Logger(),
	)
	go orch.Run(ctx)

	go func() {
		logger.Info().Str("bind", cfg.RuntimeGRPCBind).Msg("runtime grpc server started")
		if serveErr := runtimeGRPC.Serve(runtimeLis); serveErr != nil {
			logger.Error().Err(serveErr).Msg("runtime grpc server stopped with error")
			stop()
		}
	}()
	go func() {
		logger.Info().Str("bind", cfg.AdminGRPCBind).Msg("admin grpc server started")
		if serveErr := adminGRPC.Serve(adminLis); serveErr != nil {
			logger.Error().Err(serveErr).Msg("admin grpc server stopped with error")
			stop()
		}
	}()

	<-ctx.Done()
	logger.Info().Msg("shutdown signal received")
	runtimeGRPC.GracefulStop()
	adminGRPC.GracefulStop()
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

func unaryAuthInterceptor(token string) grpc.UnaryServerInterceptor {
	token = strings.TrimSpace(token)
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		if token == "" {
			return handler(ctx, req)
		}
		if !validateToken(ctx, token) {
			return nil, status.Error(codes.Unauthenticated, "invalid internal token")
		}
		return handler(ctx, req)
	}
}

func streamAuthInterceptor(token string) grpc.StreamServerInterceptor {
	token = strings.TrimSpace(token)
	return func(srv any, stream grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) error {
		if token == "" {
			return handler(srv, stream)
		}
		if !validateToken(stream.Context(), token) {
			return status.Error(codes.Unauthenticated, "invalid internal token")
		}
		return handler(srv, stream)
	}
}

func validateToken(ctx context.Context, expected string) bool {
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return false
	}
	values := md.Get("x-internal-token")
	for _, value := range values {
		if strings.TrimSpace(value) == expected {
			return true
		}
	}
	return false
}
