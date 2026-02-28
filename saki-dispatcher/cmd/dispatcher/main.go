package main

import (
	"context"
	"fmt"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

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
		log.Error().Err(err).Msg("dispatcher 异常退出")
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
		logger.Info().Msg("数据库连接已就绪")
	} else {
		logger.Warn().Msg("DATABASE_URL 为空，运行时持久化未启用")
	}

	domainClient := runtime_domain_client.New(cfg.RuntimeDomainTarget, cfg.RuntimeDomainToken, 5)
	if domainClient.Configured() {
		domainClient.Start(ctx)
		logger.Info().Str("target", cfg.RuntimeDomainTarget).Msg("runtime_domain 连接管理器已启动")
	} else {
		logger.Warn().Msg("RUNTIME_DOMAIN_TARGET 为空，runtime_domain 桥接未启用")
	}
	defer func() {
		if err := domainClient.Close(); err != nil {
			logger.Warn().Err(err).Str("target", cfg.RuntimeDomainTarget).Msg("关闭 runtime_domain 连接失败")
			return
		}
		if domainClient.Configured() {
			logger.Info().Str("target", cfg.RuntimeDomainTarget).Msg("runtime_domain 连接已关闭")
		}
	}()

	dispatcher := dispatch.NewDispatcher()
	controlPlane := controlplane.NewService(
		repository,
		dispatcher,
		domainClient,
		cfg.DispatchScanLockKey,
		cfg.SimulationRoundCooldownSec,
		cfg.StoppingForceCancelSec,
		cfg.PredictionTTLDays,
		cfg.PredictionTTLKeepRounds,
		cfg.RoundAffinityWaitSec,
		cfg.StrictTrainModelHandoff,
		logger.With().Str("service", "controlplane").Logger(),
	)
	runtimeServer := runtimegrpc.NewServer(
		dispatcher,
		controlPlane,
		domainClient,
		logger.With().Str("grpc", "runtime").Logger(),
	)
	adminServer := admingrpc.NewServer(dispatcher, controlPlane, domainClient, logger.With().Str("grpc", "admin").Logger())

	runtimeLis, err := net.Listen("tcp", cfg.RuntimeGRPCBind)
	if err != nil {
		return fmt.Errorf("监听 runtime gRPC 端口失败: %w", err)
	}
	adminLis, err := net.Listen("tcp", cfg.AdminGRPCBind)
	if err != nil {
		return fmt.Errorf("监听 admin gRPC 端口失败: %w", err)
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
		logger.Info().Str("bind", cfg.RuntimeGRPCBind).Msg("runtime gRPC 服务已启动")
		if serveErr := runtimeGRPC.Serve(runtimeLis); serveErr != nil {
			logger.Error().Err(serveErr).Msg("runtime gRPC 服务异常停止")
			stop()
		}
	}()
	go func() {
		logger.Info().Str("bind", cfg.AdminGRPCBind).Msg("admin gRPC 服务已启动")
		if serveErr := adminGRPC.Serve(adminLis); serveErr != nil {
			logger.Error().Err(serveErr).Msg("admin gRPC 服务异常停止")
			stop()
		}
	}()

	if cfg.EnableStdinCommands {
		startStdinCommandLoop(
			ctx,
			stop,
			domainClient,
			dispatcher,
			logger.With().Str("module", "stdin_cmd").Logger(),
		)
	} else {
		logger.Info().Msg("stdin 命令台未启用")
	}

	<-ctx.Done()
	logger.Info().Msg("收到退出信号，开始优雅停机")
	stopGRPCWithTimeout("runtime", runtimeGRPC, 5*time.Second, logger)
	stopGRPCWithTimeout("admin", adminGRPC, 5*time.Second, logger)
	return nil
}

func stopGRPCWithTimeout(name string, server *grpc.Server, timeout time.Duration, logger zerolog.Logger) {
	if server == nil {
		return
	}

	done := make(chan struct{})
	go func() {
		server.GracefulStop()
		close(done)
	}()

	select {
	case <-done:
		logger.Info().Str("grpc", name).Msg("gRPC 服务已优雅停止")
	case <-time.After(timeout):
		logger.Warn().
			Str("grpc", name).
			Dur("timeout", timeout).
			Msg("gRPC 优雅停止超时，执行强制停止")
		server.Stop()
		<-done
		logger.Info().Str("grpc", name).Msg("gRPC 服务已强制停止")
	}
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
			return nil, status.Error(codes.Unauthenticated, "内部令牌无效")
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
			return status.Error(codes.Unauthenticated, "内部令牌无效")
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
