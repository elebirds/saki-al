package internalrpc

import (
	"context"
	"database/sql"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestRuntimeServerRegisterTranslatesToCommand(t *testing.T) {
	registrar := &fakeRegisterExecutorHandler{
		result: &commands.ExecutorRecord{
			ID:         "executor-a",
			Version:    "1.2.3",
			LastSeenAt: time.UnixMilli(123456789),
		},
	}
	server := NewRuntimeServer(registrar, &fakeHeartbeatExecutorHandler{}, &fakeCompleteTaskHandler{})

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentIngressClient(http.DefaultClient, httpServer.URL)
	resp, err := client.Register(context.Background(), connect.NewRequest(&runtimev1.RegisterRequest{
		AgentId:      "agent-a",
		Version:      "1.2.3",
		Capabilities: []string{"gpu"},
	}))
	if err != nil {
		t.Fatalf("register executor: %v", err)
	}

	if !resp.Msg.Accepted || resp.Msg.HeartbeatIntervalMs == 0 {
		t.Fatalf("unexpected register response: %+v", resp.Msg)
	}
	if registrar.last.ExecutorID != "agent-a" || registrar.last.Version != "1.2.3" {
		t.Fatalf("unexpected register command: %+v", registrar.last)
	}
	if !slices.Equal(registrar.last.Capabilities, []string{"gpu"}) {
		t.Fatalf("unexpected register capabilities: %+v", registrar.last.Capabilities)
	}
}

func TestRuntimeServerHeartbeatTranslatesToCommand(t *testing.T) {
	heartbeats := &fakeHeartbeatExecutorHandler{}
	server := NewRuntimeServer(&fakeRegisterExecutorHandler{}, heartbeats, &fakeCompleteTaskHandler{})

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentIngressClient(http.DefaultClient, httpServer.URL)
	resp, err := client.Heartbeat(context.Background(), connect.NewRequest(&runtimev1.HeartbeatRequest{
		AgentId:      "agent-a",
		AgentVersion: "1.2.4",
		SentAtUnixMs: 123456789,
	}))
	if err != nil {
		t.Fatalf("heartbeat executor: %v", err)
	}

	if !resp.Msg.Accepted || resp.Msg.NextHeartbeatMs == 0 {
		t.Fatalf("unexpected heartbeat response: %+v", resp.Msg)
	}
	if heartbeats.last.ExecutorID != "agent-a" || heartbeats.last.SeenAt.UnixMilli() != 123456789 {
		t.Fatalf("unexpected heartbeat command: %+v", heartbeats.last)
	}
}

func TestRuntimeServerPushTaskEventCompletesTask(t *testing.T) {
	completer := &fakeCompleteTaskHandler{}
	server := NewRuntimeServer(&fakeRegisterExecutorHandler{}, &fakeHeartbeatExecutorHandler{}, completer)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentIngressClient(http.DefaultClient, httpServer.URL)
	resp, err := client.PushTaskEvent(context.Background(), connect.NewRequest(&runtimev1.PushTaskEventRequest{
		Event: &runtimev1.TaskEventEnvelope{
			AgentId:     "agent-a",
			TaskId:      "550e8400-e29b-41d4-a716-446655440000",
			ExecutionId: "exec-1",
			Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED,
		},
	}))
	if err != nil {
		t.Fatalf("push task event: %v", err)
	}
	if !resp.Msg.Accepted {
		t.Fatalf("unexpected push task event response: %+v", resp.Msg)
	}

	if completer.last.TaskID.String() != "550e8400-e29b-41d4-a716-446655440000" {
		t.Fatalf("unexpected complete task command: %+v", completer.last)
	}
}

func TestRuntimeServerRegisterAndHeartbeatPersistExecutor(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startRuntimePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	defer sqlDB.Close()

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, runtimeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	executorRepo := runtimerepo.NewExecutorRepo(pool)
	server := NewRuntimeServer(
		commands.NewRegisterExecutorHandler(executorRepo),
		commands.NewHeartbeatExecutorHandler(executorRepo),
		&fakeCompleteTaskHandler{},
	)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentIngressClient(http.DefaultClient, httpServer.URL)
	registerAt := time.UnixMilli(123456789)
	server.heartbeatInterval = time.Second
	if _, err := client.Register(context.Background(), connect.NewRequest(&runtimev1.RegisterRequest{
		AgentId:      "agent-a",
		Version:      "1.2.3",
		Capabilities: []string{"gpu", "cuda"},
	})); err != nil {
		t.Fatalf("register executor: %v", err)
	}

	heartbeatAt := registerAt.Add(2 * time.Minute)
	if _, err := client.Heartbeat(context.Background(), connect.NewRequest(&runtimev1.HeartbeatRequest{
		AgentId:      "agent-a",
		AgentVersion: "1.2.4",
		SentAtUnixMs: heartbeatAt.UnixMilli(),
	})); err != nil {
		t.Fatalf("heartbeat executor: %v", err)
	}

	executors, err := executorRepo.List(ctx)
	if err != nil {
		t.Fatalf("list executors: %v", err)
	}
	if len(executors) != 1 {
		t.Fatalf("unexpected executor count: %d", len(executors))
	}
	if executors[0].ID != "agent-a" || executors[0].Version != "1.2.3" {
		t.Fatalf("unexpected executor: %+v", executors[0])
	}
	if !slices.Equal(executors[0].Capabilities, []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected executor capabilities: %+v", executors[0].Capabilities)
	}
	if !executors[0].LastSeenAt.Equal(heartbeatAt) {
		t.Fatalf("unexpected last seen: %s", executors[0].LastSeenAt)
	}
}

type fakeRegisterExecutorHandler struct {
	last   commands.RegisterExecutorCommand
	result *commands.ExecutorRecord
}

func (f *fakeRegisterExecutorHandler) Handle(_ context.Context, cmd commands.RegisterExecutorCommand) (*commands.ExecutorRecord, error) {
	f.last = cmd
	if f.result != nil {
		return f.result, nil
	}
	return &commands.ExecutorRecord{
		ID:           cmd.ExecutorID,
		Version:      cmd.Version,
		Capabilities: slices.Clone(cmd.Capabilities),
		LastSeenAt:   cmd.SeenAt,
	}, nil
}

type fakeHeartbeatExecutorHandler struct {
	last commands.HeartbeatExecutorCommand
}

func (f *fakeHeartbeatExecutorHandler) Handle(_ context.Context, cmd commands.HeartbeatExecutorCommand) error {
	f.last = cmd
	return nil
}

type fakeCompleteTaskHandler struct {
	last commands.CompleteTaskCommand
}

func (f *fakeCompleteTaskHandler) Handle(_ context.Context, cmd commands.CompleteTaskCommand) (*commands.TaskRecord, error) {
	f.last = cmd
	return &commands.TaskRecord{}, nil
}

func startRuntimePostgres(t *testing.T, ctx context.Context) (*postgres.PostgresContainer, string) {
	t.Helper()

	container, err := postgres.Run(
		ctx,
		runtimePostgresImageRef(),
		postgres.WithDatabase("saki"),
		postgres.WithUsername("postgres"),
		postgres.WithPassword("postgres"),
		testcontainers.WithWaitStrategy(
			wait.ForLog("database system is ready to accept connections").WithOccurrence(2),
		),
	)
	if err != nil {
		t.Fatalf("start postgres container: %v", err)
	}

	dsn, err := container.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		t.Fatalf("build postgres dsn: %v", err)
	}

	return container, dsn
}

func runtimeMigrationsDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}

	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "db", "migrations")
}

func runtimePostgresImageRef() string {
	cmd := exec.Command("docker", "image", "inspect", "postgres:16-alpine", "--format", "{{.Id}}")
	output, err := cmd.Output()
	if err != nil {
		return "postgres:16-alpine"
	}

	imageID := strings.TrimSpace(string(output))
	if imageID == "" {
		return "postgres:16-alpine"
	}
	return imageID
}
