package e2e_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/elebirds/saki/saki-controlplane/internal/app/bootstrap"
	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimescheduler "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/scheduler"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/internalrpc"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestRuntimeTaskLifecycle_AssignRunSucceed(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startRuntimePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	pool := openRuntimePool(t, ctx, dsn)
	defer pool.Close()

	taskRepo := runtimerepo.NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create pending task: %v", err)
	}

	leader := runtimescheduler.NewLeaderTicker(
		runtimerepo.NewLeaseRepo(pool),
		runtimescheduler.NewDispatchScan(
			commands.NewAssignTaskHandlerWithTx(runtimerepo.NewAssignTaskTxRunner(pool)),
			"agent-e2e-1",
		),
		"runtime-scheduler",
		"runtime-e2e-1",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	assigned, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load assigned task: %v", err)
	}
	if assigned == nil || assigned.Status != "assigned" {
		t.Fatalf("expected assigned task, got %+v", assigned)
	}
	if assigned.CurrentExecutionID == "" {
		t.Fatalf("expected execution id after assignment, got %+v", assigned)
	}

	var assignPayloadBytes []byte
	if err := pool.QueryRow(ctx, `
select payload
from runtime_outbox
where aggregate_id = $1
  and topic = $2
`, taskID.String(), commands.AssignTaskOutboxTopic).Scan(&assignPayloadBytes); err != nil {
		t.Fatalf("load assign outbox: %v", err)
	}

	var assignPayload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(assignPayloadBytes, &assignPayload); err != nil {
		t.Fatalf("unmarshal assign payload: %v", err)
	}
	if assignPayload.TaskID != taskID || assignPayload.ExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("unexpected assign outbox payload: %+v", assignPayload)
	}

	controlServer := &recordingAgentControlServer{}
	controlMux := http.NewServeMux()
	controlPath, controlHandler := runtimev1connect.NewAgentControlHandler(controlServer)
	controlMux.Handle(controlPath, controlHandler)
	controlHTTPServer := httptest.NewServer(controlMux)
	defer controlHTTPServer.Close()

	dispatchWorker := runtimeeffects.NewWorker(
		runtimerepo.NewOutboxRepo(pool),
		runtimeeffects.NewDispatchEffect(connectDispatchClient{
			client: runtimev1connect.NewAgentControlClient(http.DefaultClient, controlHTTPServer.URL),
		}),
	)
	if err := dispatchWorker.RunOnce(ctx); err != nil {
		t.Fatalf("dispatch worker run once: %v", err)
	}

	if controlServer.assignTask == nil {
		t.Fatal("expected assign control rpc to be invoked")
	}
	if controlServer.assignTask.TaskId != taskID.String() {
		t.Fatalf("unexpected assign control task id: %+v", controlServer.assignTask)
	}
	if controlServer.assignTask.ExecutionId != assigned.CurrentExecutionID {
		t.Fatalf("unexpected assign control execution id: %+v", controlServer.assignTask)
	}
	if controlServer.assignTask.TaskType != "predict" {
		t.Fatalf("unexpected assign control task type: %+v", controlServer.assignTask)
	}

	var publishedAssignCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from runtime_outbox
where aggregate_id = $1
  and topic = $2
  and published_at is not null
`, taskID.String(), commands.AssignTaskOutboxTopic).Scan(&publishedAssignCount); err != nil {
		t.Fatalf("count published assign outbox: %v", err)
	}
	if publishedAssignCount != 1 {
		t.Fatalf("expected exactly one published assign outbox, got %d", publishedAssignCount)
	}

	server := internalrpc.NewRuntimeServer(
		noopRegisterAgentHandler{},
		noopHeartbeatAgentHandler{},
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, runtimerepo.NewCommandOutboxWriter(pool)),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	mux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(ingressPath, ingressHandler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentIngressClient(http.DefaultClient, httpServer.URL)
	if _, err := client.PushTaskEvent(ctx, connect.NewRequest(&runtimev1.PushTaskEventRequest{
		Event: &runtimev1.TaskEventEnvelope{
			AgentId:     "agent-e2e-1",
			TaskId:      taskID.String(),
			ExecutionId: assigned.CurrentExecutionID,
			Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING,
		},
	})); err != nil {
		t.Fatalf("ingress running event: %v", err)
	}
	running, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load running task: %v", err)
	}
	if running == nil || running.Status != "running" {
		t.Fatalf("expected running task, got %+v", running)
	}
	if _, err := client.PushTaskEvent(ctx, connect.NewRequest(&runtimev1.PushTaskEventRequest{
		Event: &runtimev1.TaskEventEnvelope{
			AgentId:     "agent-e2e-1",
			TaskId:      taskID.String(),
			ExecutionId: assigned.CurrentExecutionID,
			Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED,
		},
	})); err != nil {
		t.Fatalf("ingress succeeded event: %v", err)
	}

	succeeded, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load succeeded task: %v", err)
	}
	if succeeded == nil || succeeded.Status != "succeeded" {
		t.Fatalf("expected succeeded task, got %+v", succeeded)
	}
}

func TestRuntimeTaskLifecycle_CancelPathWritesStopOutbox(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startRuntimePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	pool := openRuntimePool(t, ctx, dsn)
	defer pool.Close()

	leaseRepo := runtimerepo.NewLeaseRepo(pool)
	lease, err := leaseRepo.AcquireOrRenew(ctx, runtimerepo.AcquireLeaseParams{
		Name:       "runtime-scheduler",
		Holder:     "runtime-e2e-2",
		LeaseUntil: time.Now().Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("acquire lease: %v", err)
	}

	taskRepo := runtimerepo.NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create pending task: %v", err)
	}

	assigned, err := taskRepo.AssignPendingTask(ctx, runtimerepo.AssignTaskParams{
		AssignedAgentID: "agent-e2e-2",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
	}
	t.Setenv("DATABASE_DSN", dsn)
	t.Setenv("AUTH_TOKEN_SECRET", "runtime-e2e-secret")
	t.Setenv("AUTH_TOKEN_TTL", "1h")
	t.Setenv("PUBLIC_API_BIND", "127.0.0.1:0")
	objectServer := newRuntimeObjectServer(t)
	defer objectServer.Close()
	setRuntimeObjectStorageEnv(t, objectServer)

	server, _, err := bootstrap.NewPublicAPI(ctx)
	if err != nil {
		t.Fatalf("bootstrap public api: %v", err)
	}
	httpServer := httptest.NewServer(server.Handler)
	defer httpServer.Close()

	req, err := http.NewRequest(http.MethodPost, httpServer.URL+"/runtime/tasks/"+taskID.String()+"/cancel", nil)
	if err != nil {
		t.Fatalf("new cancel request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post cancel request: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted {
		t.Fatalf("unexpected cancel status: %d", resp.StatusCode)
	}

	var body map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode cancel response: %v", err)
	}
	if accepted, _ := body["accepted"].(bool); !accepted {
		t.Fatalf("unexpected cancel response body: %+v", body)
	}

	canceled, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load task after cancel: %v", err)
	}
	if canceled == nil || canceled.Status != "cancel_requested" {
		t.Fatalf("expected cancel_requested task, got %+v", canceled)
	}

	var payloadBytes []byte
	var stopOutboxCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from runtime_outbox
where aggregate_id = $1
  and topic = $2
`, taskID.String(), commands.StopTaskOutboxTopic).Scan(&stopOutboxCount); err != nil {
		t.Fatalf("count stop outbox: %v", err)
	}
	if stopOutboxCount != 1 {
		t.Fatalf("expected exactly one stop outbox, got %d", stopOutboxCount)
	}

	if err := pool.QueryRow(ctx, `
select payload
from runtime_outbox
where aggregate_id = $1
  and topic = $2
order by id desc
limit 1
`, taskID.String(), commands.StopTaskOutboxTopic).Scan(&payloadBytes); err != nil {
		t.Fatalf("load stop outbox: %v", err)
	}

	var payload commands.StopTaskOutboxPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("unmarshal stop payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("unexpected stop task id: %+v", payload)
	}
	if payload.ExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("unexpected stop execution id: %+v", payload)
	}
	if payload.AgentID != "agent-e2e-2" {
		t.Fatalf("unexpected stop agent id: %+v", payload)
	}
	if payload.Reason != "cancel_requested" {
		t.Fatalf("unexpected stop reason: %+v", payload)
	}
	if payload.LeaderEpoch != lease.Epoch {
		t.Fatalf("unexpected stop leader epoch: %+v", payload)
	}
}

type noopRegisterAgentHandler struct{}

func (noopRegisterAgentHandler) Handle(context.Context, commands.RegisterAgentCommand) (*commands.AgentRecord, error) {
	return &commands.AgentRecord{}, nil
}

type noopHeartbeatAgentHandler struct{}

func (noopHeartbeatAgentHandler) Handle(context.Context, commands.HeartbeatAgentCommand) error {
	return nil
}

type connectDispatchClient struct {
	client runtimev1connect.AgentControlClient
}

func (c connectDispatchClient) AssignTask(ctx context.Context, req *runtimev1.AssignTaskRequest) error {
	_, err := c.client.AssignTask(ctx, connect.NewRequest(req))
	return err
}

type recordingAgentControlServer struct {
	runtimev1connect.UnimplementedAgentControlHandler
	assignTask *runtimev1.AssignTaskRequest
	stopTask   *runtimev1.StopTaskRequest
}

func (s *recordingAgentControlServer) AssignTask(_ context.Context, req *connect.Request[runtimev1.AssignTaskRequest]) (*connect.Response[runtimev1.AssignTaskResponse], error) {
	s.assignTask = req.Msg
	return connect.NewResponse(&runtimev1.AssignTaskResponse{Accepted: true}), nil
}

func (s *recordingAgentControlServer) StopTask(_ context.Context, req *connect.Request[runtimev1.StopTaskRequest]) (*connect.Response[runtimev1.StopTaskResponse], error) {
	s.stopTask = req.Msg
	return connect.NewResponse(&runtimev1.StopTaskResponse{Accepted: true}), nil
}

type runtimeObjectServer struct {
	server  *httptest.Server
	mu      sync.RWMutex
	objects map[string]runtimeStoredObject
}

type runtimeStoredObject struct {
	body        []byte
	contentType string
}

func newRuntimeObjectServer(t *testing.T) *runtimeObjectServer {
	t.Helper()

	s := &runtimeObjectServer{
		objects: make(map[string]runtimeStoredObject),
	}
	s.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key := strings.TrimPrefix(r.URL.Path, "/assets/")
		if key == r.URL.Path || key == "" {
			http.NotFound(w, r)
			return
		}

		switch r.Method {
		case http.MethodPut:
			body, err := io.ReadAll(r.Body)
			if err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			s.mu.Lock()
			s.objects[key] = runtimeStoredObject{
				body:        body,
				contentType: r.Header.Get("Content-Type"),
			}
			s.mu.Unlock()
			w.WriteHeader(http.StatusNoContent)
		case http.MethodHead:
			s.mu.RLock()
			obj, ok := s.objects[key]
			s.mu.RUnlock()
			if !ok {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("ETag", "\"runtime-etag\"")
			w.Header().Set("Last-Modified", "Mon, 02 Jan 2006 15:04:05 GMT")
			w.Header().Set("Content-Length", strconv.Itoa(len(obj.body)))
			w.Header().Set("Content-Type", obj.contentType)
			w.WriteHeader(http.StatusOK)
		case http.MethodGet:
			s.mu.RLock()
			obj, ok := s.objects[key]
			s.mu.RUnlock()
			if !ok {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("ETag", "\"runtime-etag\"")
			w.Header().Set("Last-Modified", "Mon, 02 Jan 2006 15:04:05 GMT")
			w.Header().Set("Content-Length", strconv.Itoa(len(obj.body)))
			w.Header().Set("Content-Type", obj.contentType)
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(obj.body)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}))
	return s
}

func (s *runtimeObjectServer) Close() {
	s.server.Close()
}

func setRuntimeObjectStorageEnv(t *testing.T, s *runtimeObjectServer) {
	t.Helper()

	t.Setenv("MINIO_ENDPOINT", strings.TrimPrefix(s.server.URL, "http://"))
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "false")
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

func openRuntimePool(t *testing.T, ctx context.Context, dsn string) *pgxpool.Pool {
	t.Helper()

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open sql db: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, runtimeMigrationsDir(t)); err != nil {
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	return pool
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
