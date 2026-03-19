package main

import (
	"context"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/internalrpc"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"
)

const (
	defaultRelayBind       = ":8082"
	defaultReadHeaderTimeout = 5 * time.Second
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	dsn := os.Getenv("DATABASE_DSN")
	if dsn == "" {
		slog.Error("relay requires DATABASE_DSN")
		os.Exit(1)
	}

	bind := os.Getenv("RELAY_BIND")
	if bind == "" {
		bind = defaultRelayBind
	}
	relayID := os.Getenv("RELAY_ID")
	if relayID == "" {
		relayID = relayBaseURLFromBind(bind)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		slog.Error("open relay database failed", "err", err)
		os.Exit(1)
	}
	defer pool.Close()

	server := internalrpc.NewRelayServer(relayID, runtimerepo.NewAgentSessionRepo(pool))
	path, handler := runtimev1connect.NewAgentRelayHandler(server)

	mux := http.NewServeMux()
	mux.Handle(path, handler)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	httpServer := &http.Server{
		Addr:              bind,
		Handler:           h2c.NewHandler(mux, &http2.Server{}),
		ReadHeaderTimeout: defaultReadHeaderTimeout,
	}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(shutdownCtx)
	}()

	slog.Info("starting relay", "addr", bind, "relay_id", relayID)
	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("relay exited", "err", err)
		os.Exit(1)
	}
}

func relayBaseURLFromBind(bind string) string {
	host, port, err := net.SplitHostPort(bind)
	if err != nil {
		return ""
	}
	switch host {
	case "", "0.0.0.0", "::":
		host = "127.0.0.1"
	}
	return "http://" + net.JoinHostPort(host, port)
}
