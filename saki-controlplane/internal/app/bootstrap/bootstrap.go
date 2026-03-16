package bootstrap

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/config"
	"github.com/elebirds/saki/saki-controlplane/internal/app/observe"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	systemapi "github.com/elebirds/saki/saki-controlplane/internal/modules/system/apihttp"
)

func NewPublicAPI(_ context.Context) (*http.Server, *slog.Logger, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, nil, err
	}

	logger := observe.NewLogger("public-api", observe.ParseLevel(cfg.LogLevel))
	tokenTTL, err := time.ParseDuration(cfg.AuthTokenTTL)
	if err != nil {
		return nil, nil, err
	}

	handler, err := systemapi.NewHTTPHandler(systemapi.Dependencies{
		Authenticator: accessapp.NewAuthenticator(cfg.AuthTokenSecret, tokenTTL),
		ProjectStore:  projectapp.NewMemoryStore(),
		RuntimeStore:  runtimequeries.NewMemoryAdminStore(),
	})
	if err != nil {
		return nil, nil, err
	}

	return &http.Server{
		Addr:              cfg.PublicAPIBind,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}, logger, nil
}

func NewRuntime(_ context.Context) (*http.Server, *slog.Logger, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, nil, err
	}

	logger := observe.NewLogger("runtime", observe.ParseLevel(cfg.LogLevel))
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	return &http.Server{
		Addr:              cfg.RuntimeBind,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}, logger, nil
}
