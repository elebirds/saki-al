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
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
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
	server := NewRuntimeServer(
		registrar,
		&fakeHeartbeatExecutorHandler{},
		&fakeStartTaskHandler{},
		&fakeCompleteTaskHandler{},
		&fakeFailTaskHandler{},
		&fakeConfirmCanceledTaskHandler{},
	)

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
	server := NewRuntimeServer(
		&fakeRegisterExecutorHandler{},
		heartbeats,
		&fakeStartTaskHandler{},
		&fakeCompleteTaskHandler{},
		&fakeFailTaskHandler{},
		&fakeConfirmCanceledTaskHandler{},
	)

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
	taskID := uuid.MustParse("550e8400-e29b-41d4-a716-446655440000")
	store := newRuntimeTaskEventStore(&commands.TaskRecord{
		ID:                 taskID,
		Status:             string(state.TaskStatusRunning),
		CurrentExecutionID: "exec-1",
		AssignedAgentID:    "agent-a",
		LeaderEpoch:        7,
	})
	server := newTaskEventRuntimeServer(store)

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
	if got := store.mustGet(t, taskID); got.Status != string(state.TaskStatusSucceeded) {
		t.Fatalf("expected task to be succeeded, got %+v", got)
	}
}

func TestAgentIngressRunningEventStartsAssignedTask(t *testing.T) {
	taskID := uuid.New()
	store := newRuntimeTaskEventStore(&commands.TaskRecord{
		ID:                 taskID,
		Status:             string(state.TaskStatusAssigned),
		CurrentExecutionID: "exec-running-1",
		AssignedAgentID:    "agent-a",
		LeaderEpoch:        7,
	})
	server := newTaskEventRuntimeServer(store)

	if err := server.IngestTaskEvent(context.Background(), &runtimev1.TaskEventEnvelope{
		AgentId:     "agent-a",
		TaskId:      taskID.String(),
		ExecutionId: "exec-running-1",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING,
	}); err != nil {
		t.Fatalf("ingest running event: %v", err)
	}

	if got := store.mustGet(t, taskID); got.Status != string(state.TaskStatusRunning) {
		t.Fatalf("expected task to be running, got %+v", got)
	}
}

func TestAgentIngressIgnoresStaleExecutionID(t *testing.T) {
	taskID := uuid.New()
	store := newRuntimeTaskEventStore(&commands.TaskRecord{
		ID:                 taskID,
		Status:             string(state.TaskStatusRunning),
		CurrentExecutionID: "exec-current",
		AssignedAgentID:    "agent-a",
		LeaderEpoch:        7,
	})
	server := newTaskEventRuntimeServer(store)

	if err := server.IngestTaskEvent(context.Background(), &runtimev1.TaskEventEnvelope{
		AgentId:     "agent-a",
		TaskId:      taskID.String(),
		ExecutionId: "exec-stale",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED,
	}); err != nil {
		t.Fatalf("ingest stale task event: %v", err)
	}

	got := store.mustGet(t, taskID)
	if got.Status != string(state.TaskStatusRunning) {
		t.Fatalf("expected stale execution to be ignored, got %+v", got)
	}
	if store.lastOutbox != nil {
		t.Fatalf("expected no outbox side effect for stale execution, got %+v", store.lastOutbox)
	}
}

func TestAgentIngressIgnoresLateRunningEventAfterSucceeded(t *testing.T) {
	taskID := uuid.New()
	store := newRuntimeTaskEventStore(&commands.TaskRecord{
		ID:                 taskID,
		Status:             string(state.TaskStatusSucceeded),
		CurrentExecutionID: "exec-current",
		AssignedAgentID:    "agent-a",
		LeaderEpoch:        7,
	})
	server := newTaskEventRuntimeServer(store)

	if err := server.IngestTaskEvent(context.Background(), &runtimev1.TaskEventEnvelope{
		AgentId:     "agent-a",
		TaskId:      taskID.String(),
		ExecutionId: "exec-current",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING,
	}); err != nil {
		t.Fatalf("ingest late running event: %v", err)
	}

	if got := store.mustGet(t, taskID); got.Status != string(state.TaskStatusSucceeded) {
		t.Fatalf("expected late running event to be ignored, got %+v", got)
	}
}

func TestAgentIngressFailedEventMarksTaskFailed(t *testing.T) {
	taskID := uuid.New()
	store := newRuntimeTaskEventStore(&commands.TaskRecord{
		ID:                 taskID,
		Status:             string(state.TaskStatusRunning),
		CurrentExecutionID: "exec-failed-1",
		AssignedAgentID:    "agent-a",
		LeaderEpoch:        7,
	})
	server := newTaskEventRuntimeServer(store)

	if err := server.IngestTaskEvent(context.Background(), &runtimev1.TaskEventEnvelope{
		AgentId:     "agent-a",
		TaskId:      taskID.String(),
		ExecutionId: "exec-failed-1",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_FAILED,
	}); err != nil {
		t.Fatalf("ingest failed event: %v", err)
	}

	if got := store.mustGet(t, taskID); got.Status != string(state.TaskStatusFailed) {
		t.Fatalf("expected task to be failed, got %+v", got)
	}
}

func TestAgentIngressCanceledEventMarksTaskCanceled(t *testing.T) {
	taskID := uuid.New()
	store := newRuntimeTaskEventStore(&commands.TaskRecord{
		ID:                 taskID,
		Status:             string(state.TaskStatusCancelRequested),
		CurrentExecutionID: "exec-canceled-1",
		AssignedAgentID:    "agent-a",
		LeaderEpoch:        7,
	})
	server := newTaskEventRuntimeServer(store)

	if err := server.IngestTaskEvent(context.Background(), &runtimev1.TaskEventEnvelope{
		AgentId:     "agent-a",
		TaskId:      taskID.String(),
		ExecutionId: "exec-canceled-1",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_CANCELED,
	}); err != nil {
		t.Fatalf("ingest canceled event: %v", err)
	}

	if got := store.mustGet(t, taskID); got.Status != string(state.TaskStatusCanceled) {
		t.Fatalf("expected task to be canceled, got %+v", got)
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
		&fakeStartTaskHandler{},
		&fakeCompleteTaskHandler{},
		&fakeFailTaskHandler{},
		&fakeConfirmCanceledTaskHandler{},
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

type fakeStartTaskHandler struct {
	last commands.StartTaskCommand
}

func (f *fakeStartTaskHandler) Handle(_ context.Context, cmd commands.StartTaskCommand) (*commands.TaskRecord, error) {
	f.last = cmd
	return &commands.TaskRecord{}, nil
}

type fakeCompleteTaskHandler struct {
	last commands.CompleteTaskCommand
}

func (f *fakeCompleteTaskHandler) Handle(_ context.Context, cmd commands.CompleteTaskCommand) (*commands.TaskRecord, error) {
	f.last = cmd
	return &commands.TaskRecord{}, nil
}

type fakeFailTaskHandler struct {
	last commands.FailTaskCommand
}

func (f *fakeFailTaskHandler) Handle(_ context.Context, cmd commands.FailTaskCommand) (*commands.TaskRecord, error) {
	f.last = cmd
	return &commands.TaskRecord{}, nil
}

type fakeConfirmCanceledTaskHandler struct {
	last commands.ConfirmTaskCanceledCommand
}

func (f *fakeConfirmCanceledTaskHandler) Handle(_ context.Context, cmd commands.ConfirmTaskCanceledCommand) (*commands.TaskRecord, error) {
	f.last = cmd
	return &commands.TaskRecord{}, nil
}

type runtimeTaskEventStore struct {
	mu         sync.Mutex
	tasks      map[uuid.UUID]*commands.TaskRecord
	lastOutbox *commands.OutboxEvent
}

func newRuntimeTaskEventStore(tasks ...*commands.TaskRecord) *runtimeTaskEventStore {
	store := &runtimeTaskEventStore{
		tasks: make(map[uuid.UUID]*commands.TaskRecord, len(tasks)),
	}
	for _, task := range tasks {
		copied := *task
		store.tasks[task.ID] = &copied
	}
	return store
}

func newTaskEventRuntimeServer(store *runtimeTaskEventStore) *RuntimeServer {
	return NewRuntimeServer(
		&fakeRegisterExecutorHandler{},
		&fakeHeartbeatExecutorHandler{},
		commands.NewStartTaskHandler(store),
		commands.NewCompleteTaskHandler(store, store),
		commands.NewFailTaskHandler(store),
		commands.NewConfirmTaskCanceledHandler(store),
	)
}

func (s *runtimeTaskEventStore) GetTask(_ context.Context, taskID uuid.UUID) (*commands.TaskRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	task, ok := s.tasks[taskID]
	if !ok {
		return nil, nil
	}
	copied := *task
	return &copied, nil
}

func (s *runtimeTaskEventStore) AdvanceTaskByExecution(_ context.Context, params commands.AdvanceTaskByExecutionParams) (*commands.TaskRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	task, ok := s.tasks[params.ID]
	if !ok {
		return nil, nil
	}
	if task.CurrentExecutionID != params.ExecutionID {
		return nil, nil
	}
	if !slices.Contains(params.FromStatuses, task.Status) {
		return nil, nil
	}

	task.Status = params.ToStatus
	copied := *task
	return &copied, nil
}

func (s *runtimeTaskEventStore) Append(_ context.Context, event commands.OutboxEvent) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	copied := event
	copied.Payload = append([]byte(nil), event.Payload...)
	s.lastOutbox = &copied
	return nil
}

func (s *runtimeTaskEventStore) mustGet(t *testing.T, taskID uuid.UUID) *commands.TaskRecord {
	t.Helper()

	task, err := s.GetTask(context.Background(), taskID)
	if err != nil {
		t.Fatalf("get task: %v", err)
	}
	if task == nil {
		t.Fatalf("task %s not found", taskID)
	}
	return task
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
