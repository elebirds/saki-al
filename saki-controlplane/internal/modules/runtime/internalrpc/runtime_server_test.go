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
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
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
	registrar := &fakeRegisterAgentHandler{
		result: &commands.AgentRecord{
			ID:         "agent-a",
			Version:    "1.2.3",
			LastSeenAt: time.UnixMilli(123456789),
		},
	}
	server := NewRuntimeServer(
		registrar,
		&fakeHeartbeatAgentHandler{},
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
		AgentId:        "agent-a",
		Version:        "1.2.3",
		Capabilities:   []string{"gpu"},
		TransportMode:  "pull",
		MaxConcurrency: 2,
	}))
	if err != nil {
		t.Fatalf("register agent: %v", err)
	}

	if !resp.Msg.Accepted || resp.Msg.HeartbeatIntervalMs == 0 {
		t.Fatalf("unexpected register response: %+v", resp.Msg)
	}
	if registrar.last.AgentID != "agent-a" || registrar.last.Version != "1.2.3" {
		t.Fatalf("unexpected register command: %+v", registrar.last)
	}
	if !slices.Equal(registrar.last.Capabilities, []string{"gpu"}) {
		t.Fatalf("unexpected register capabilities: %+v", registrar.last.Capabilities)
	}
	if registrar.last.TransportMode != "pull" || registrar.last.MaxConcurrency != 2 {
		t.Fatalf("unexpected register scheduling facts: %+v", registrar.last)
	}
}

func TestRegisterAgentRequestCarriesAgentIdentity(t *testing.T) {
	registrar := &fakeRegisterAgentHandler{
		result: &commands.AgentRecord{
			ID:         "agent-z",
			Version:    "9.9.9",
			LastSeenAt: time.UnixMilli(987654321),
		},
	}
	server := NewRuntimeServer(
		registrar,
		&fakeHeartbeatAgentHandler{},
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
	if _, err := client.Register(context.Background(), connect.NewRequest(&runtimev1.RegisterRequest{
		AgentId:        "agent-z",
		Version:        "9.9.9",
		Capabilities:   []string{"gpu", "cuda"},
		TransportMode:  "direct",
		ControlBaseUrl: "http://127.0.0.1:18081",
		MaxConcurrency: 4,
	})); err != nil {
		t.Fatalf("register agent: %v", err)
	}

	if registrar.last.AgentID != "agent-z" || registrar.last.Version != "9.9.9" {
		t.Fatalf("unexpected register agent command: %+v", registrar.last)
	}
	if !slices.Equal(registrar.last.Capabilities, []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected register agent capabilities: %+v", registrar.last.Capabilities)
	}
	if registrar.last.TransportMode != "direct" || registrar.last.ControlBaseURL != "http://127.0.0.1:18081" || registrar.last.MaxConcurrency != 4 {
		t.Fatalf("unexpected register agent scheduling facts: %+v", registrar.last)
	}
}

func TestRuntimeServerHeartbeatTranslatesToCommand(t *testing.T) {
	heartbeats := &fakeHeartbeatAgentHandler{}
	server := NewRuntimeServer(
		&fakeRegisterAgentHandler{},
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
		AgentId:        "agent-a",
		AgentVersion:   "1.2.4",
		RunningTaskIds: []string{"task-1", "task-2"},
		MaxConcurrency: 3,
		SentAtUnixMs:   123456789,
	}))
	if err != nil {
		t.Fatalf("heartbeat agent: %v", err)
	}

	if !resp.Msg.Accepted || resp.Msg.NextHeartbeatMs == 0 {
		t.Fatalf("unexpected heartbeat response: %+v", resp.Msg)
	}
	if heartbeats.last.AgentID != "agent-a" || heartbeats.last.Version != "1.2.4" || heartbeats.last.SeenAt.UnixMilli() != 123456789 {
		t.Fatalf("unexpected heartbeat command: %+v", heartbeats.last)
	}
	if !slices.Equal(heartbeats.last.RunningTaskIDs, []string{"task-1", "task-2"}) || heartbeats.last.MaxConcurrency != 3 {
		t.Fatalf("unexpected heartbeat scheduling facts: %+v", heartbeats.last)
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

func TestRuntimeInternalRPCMountsAgentIngressAndArtifactService(t *testing.T) {
	assetID := uuid.New()
	registrar := &fakeRegisterAgentHandler{}
	uploads := &fakeIssueUploadTicketHandler{
		result: &assetapp.Ticket{
			AssetID: assetID,
			URL:     "https://upload.example.test",
		},
	}
	runtimeServer := NewRuntimeServer(
		registrar,
		&fakeHeartbeatAgentHandler{},
		&fakeStartTaskHandler{},
		&fakeCompleteTaskHandler{},
		&fakeFailTaskHandler{},
		&fakeConfirmCanceledTaskHandler{},
	)
	artifactServer := NewArtifactServer(uploads, &fakeIssueDownloadTicketHandler{})

	mux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(runtimeServer)
	mux.Handle(ingressPath, ingressHandler)
	artifactPath, artifactHandler := runtimev1connect.NewArtifactServiceHandler(artifactServer)
	mux.Handle(artifactPath, artifactHandler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	ingressClient := runtimev1connect.NewAgentIngressClient(http.DefaultClient, httpServer.URL)
	ingressResp, err := ingressClient.Register(context.Background(), connect.NewRequest(&runtimev1.RegisterRequest{
		AgentId:      "agent-combined",
		Version:      "1.2.3",
		Capabilities: []string{"gpu"},
	}))
	if err != nil {
		t.Fatalf("agent ingress register: %v", err)
	}
	if !ingressResp.Msg.GetAccepted() {
		t.Fatalf("expected register accepted, got %+v", ingressResp.Msg)
	}
	if registrar.last.AgentID != "agent-combined" {
		t.Fatalf("unexpected register command: %+v", registrar.last)
	}

	artifactClient := runtimev1connect.NewArtifactServiceClient(http.DefaultClient, httpServer.URL)
	artifactResp, err := artifactClient.CreateUploadTicket(context.Background(), connect.NewRequest(&runtimev1.CreateUploadTicketRequest{
		ArtifactId: assetID.String(),
	}))
	if err != nil {
		t.Fatalf("artifact create upload ticket: %v", err)
	}
	if uploads.lastAssetID != assetID {
		t.Fatalf("unexpected upload ticket asset id: got=%s want=%s", uploads.lastAssetID, assetID)
	}
	if got, want := artifactResp.Msg.GetUrl(), "https://upload.example.test"; got != want {
		t.Fatalf("unexpected upload ticket url: got=%q want=%q", got, want)
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

	agentRepo := runtimerepo.NewAgentRepo(pool)
	server := NewRuntimeServer(
		commands.NewRegisterAgentHandler(agentRepo),
		commands.NewHeartbeatAgentHandler(agentRepo),
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
		AgentId:        "agent-a",
		Version:        "1.2.3",
		Capabilities:   []string{"gpu", "cuda"},
		TransportMode:  "pull",
		MaxConcurrency: 2,
	})); err != nil {
		t.Fatalf("register agent: %v", err)
	}

	heartbeatAt := registerAt.Add(2 * time.Minute)
	if _, err := client.Heartbeat(context.Background(), connect.NewRequest(&runtimev1.HeartbeatRequest{
		AgentId:        "agent-a",
		AgentVersion:   "1.2.4",
		RunningTaskIds: []string{"task-1", "task-2"},
		MaxConcurrency: 3,
		SentAtUnixMs:   heartbeatAt.UnixMilli(),
	})); err != nil {
		t.Fatalf("heartbeat agent: %v", err)
	}

	agents, err := agentRepo.List(ctx)
	if err != nil {
		t.Fatalf("list agents: %v", err)
	}
	if len(agents) != 1 {
		t.Fatalf("unexpected agent count: %d", len(agents))
	}
	if agents[0].ID != "agent-a" || agents[0].Version != "1.2.4" {
		t.Fatalf("unexpected agent: %+v", agents[0])
	}
	if !slices.Equal(agents[0].Capabilities, []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected agent capabilities: %+v", agents[0].Capabilities)
	}
	if agents[0].TransportMode != "pull" || agents[0].MaxConcurrency != 3 {
		t.Fatalf("unexpected agent scheduling facts: %+v", agents[0])
	}
	if !slices.Equal(agents[0].RunningTaskIDs, []string{"task-1", "task-2"}) {
		t.Fatalf("unexpected agent running task ids: %+v", agents[0].RunningTaskIDs)
	}
	if !agents[0].LastSeenAt.Equal(heartbeatAt) {
		t.Fatalf("unexpected last seen: %s", agents[0].LastSeenAt)
	}
}

type fakeRegisterAgentHandler struct {
	last   commands.RegisterAgentCommand
	result *commands.AgentRecord
}

func (f *fakeRegisterAgentHandler) Handle(_ context.Context, cmd commands.RegisterAgentCommand) (*commands.AgentRecord, error) {
	f.last = cmd
	if f.result != nil {
		return f.result, nil
	}

	return &commands.AgentRecord{
		ID:             cmd.AgentID,
		Version:        cmd.Version,
		Capabilities:   slices.Clone(cmd.Capabilities),
		TransportMode:  cmd.TransportMode,
		ControlBaseURL: cmd.ControlBaseURL,
		MaxConcurrency: cmd.MaxConcurrency,
		LastSeenAt:     cmd.SeenAt,
	}, nil
}

type fakeHeartbeatAgentHandler struct {
	last commands.HeartbeatAgentCommand
}

func (f *fakeHeartbeatAgentHandler) Handle(_ context.Context, cmd commands.HeartbeatAgentCommand) error {
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
	mu    sync.Mutex
	tasks map[uuid.UUID]*commands.TaskRecord
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
		&fakeRegisterAgentHandler{},
		&fakeHeartbeatAgentHandler{},
		commands.NewStartTaskHandler(store),
		commands.NewCompleteTaskHandler(store),
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
