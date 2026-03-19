package apihttp_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/apihttp"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestRuntimeAdminQueriesReadPersistedState(t *testing.T) {
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
		Holder:     "runtime-1",
		LeaseUntil: time.Now().Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("acquire lease: %v", err)
	}

	taskRepo := runtimerepo.NewTaskRepo(pool)
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       uuid.New(),
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create pending task: %v", err)
	}
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       uuid.New(),
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create claimable task: %v", err)
	}
	if _, err := taskRepo.AssignPendingTask(ctx, runtimerepo.AssignTaskParams{
		AssignedAgentID: "agent-runtime-1",
		LeaderEpoch:     lease.Epoch,
	}); err != nil {
		t.Fatalf("assign task: %v", err)
	}

	agentRepo := runtimerepo.NewAgentRepo(pool)
	if _, err := agentRepo.Upsert(ctx, runtimerepo.UpsertAgentParams{
		ID:             "agent-a",
		Version:        "1.2.3",
		Capabilities:   []string{"gpu"},
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     time.UnixMilli(123456789),
	}); err != nil {
		t.Fatalf("register agent: %v", err)
	}

	handlers := apihttp.NewHandlers(
		apihttp.Dependencies{
			Store:    runtimequeries.NewRepoAdminStore(taskRepo, agentRepo),
			Commands: runtimequeries.NewIssueRuntimeCommandUseCase(&fakeRuntimeCanceler{}),
		},
	)

	summary, err := handlers.GetRuntimeSummary(ctx)
	if err != nil {
		t.Fatalf("get runtime summary: %v", err)
	}
	if summary.PendingTasks != 1 || summary.RunningTasks != 1 || summary.LeaderEpoch != lease.Epoch {
		t.Fatalf("unexpected runtime summary: %+v", summary)
	}
}

func TestListRuntimeAgents(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	container, dsn := startRuntimePostgres(t, ctx)
	defer func() {
		_ = testcontainers.TerminateContainer(container)
	}()

	pool := openRuntimePool(t, ctx, dsn)
	defer pool.Close()

	taskRepo := runtimerepo.NewTaskRepo(pool)
	agentRepo := runtimerepo.NewAgentRepo(pool)
	if _, err := agentRepo.Upsert(ctx, runtimerepo.UpsertAgentParams{
		ID:             "agent-a",
		Version:        "1.2.3",
		Capabilities:   []string{"gpu"},
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     time.UnixMilli(123456789),
	}); err != nil {
		t.Fatalf("register agent: %v", err)
	}

	handlers := apihttp.NewHandlers(
		apihttp.Dependencies{
			Store:    runtimequeries.NewRepoAdminStore(taskRepo, agentRepo),
			Commands: runtimequeries.NewIssueRuntimeCommandUseCase(&fakeRuntimeCanceler{}),
		},
	)

	agents, err := handlers.ListRuntimeAgents(ctx)
	if err != nil {
		t.Fatalf("list runtime agents: %v", err)
	}
	if len(agents) != 1 || agents[0].ID != "agent-a" || agents[0].Version != "1.2.3" {
		t.Fatalf("unexpected agents: %+v", agents)
	}
}

func TestRuntimeAdminCancelTaskTransitionsTask(t *testing.T) {
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
		t.Fatalf("create task: %v", err)
	}

	handlers := apihttp.NewHandlers(
		apihttp.Dependencies{
			Store: runtimequeries.NewRepoAdminStore(taskRepo, runtimerepo.NewAgentRepo(pool)),
			Commands: runtimequeries.NewIssueRuntimeCommandUseCase(
				commands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)),
			),
		},
	)

	resp, err := handlers.CancelRuntimeTask(ctx, openapi.CancelRuntimeTaskParams{TaskID: taskID.String()})
	if err != nil {
		t.Fatalf("cancel runtime task: %v", err)
	}
	if !resp.Accepted {
		t.Fatalf("unexpected cancel response: %+v", resp)
	}

	task, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load task: %v", err)
	}
	if task == nil || task.Status != "canceled" {
		t.Fatalf("unexpected canceled task: %+v", task)
	}

	var commandCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from agent_command
where task_id = $1
  and command_type = 'cancel'
`, taskID).Scan(&commandCount); err != nil {
		t.Fatalf("count cancel commands: %v", err)
	}
	if commandCount != 0 {
		t.Fatalf("expected no cancel command for pending cancel, got %d", commandCount)
	}
}

func TestCancelRuntimeTaskUsesCommandPath(t *testing.T) {
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
		Holder:     "runtime-1",
		LeaseUntil: time.Now().Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("acquire lease: %v", err)
	}

	taskRepo := runtimerepo.NewTaskRepo(pool)
	agentRepo := runtimerepo.NewAgentRepo(pool)
	assignmentRepo := runtimerepo.NewTaskAssignmentRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create task: %v", err)
	}

	if _, err := agentRepo.Upsert(ctx, runtimerepo.UpsertAgentParams{
		ID:             "agent-runtime-1",
		Version:        "test",
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     time.Now().UTC(),
	}); err != nil {
		t.Fatalf("register agent: %v", err)
	}

	assigned, err := taskRepo.AssignPendingTask(ctx, runtimerepo.AssignTaskParams{
		AssignedAgentID: "agent-runtime-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
	}
	if _, err := assignmentRepo.Create(ctx, runtimerepo.CreateTaskAssignmentParams{
		TaskID:      taskID,
		Attempt:     1,
		AgentID:     "agent-runtime-1",
		ExecutionID: assigned.CurrentExecutionID,
		Status:      "assigned",
	}); err != nil {
		t.Fatalf("create assignment: %v", err)
	}

	handlers := apihttp.NewHandlers(
		apihttp.Dependencies{
			Store: runtimequeries.NewRepoAdminStore(taskRepo, agentRepo),
			Commands: runtimequeries.NewIssueRuntimeCommandUseCase(
				commands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)),
			),
		},
	)

	resp, err := handlers.CancelRuntimeTask(ctx, openapi.CancelRuntimeTaskParams{TaskID: taskID.String()})
	if err != nil {
		t.Fatalf("cancel runtime task: %v", err)
	}
	if !resp.Accepted {
		t.Fatalf("unexpected cancel response: %+v", resp)
	}

	task, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("load task: %v", err)
	}
	if task == nil || task.Status != "cancel_requested" {
		t.Fatalf("unexpected canceled task: %+v", task)
	}

	var payloadBytes []byte
	var stopCommandCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from agent_command
where task_id = $1
  and command_type = 'cancel'
`, taskID).Scan(&stopCommandCount); err != nil {
		t.Fatalf("count cancel commands: %v", err)
	}
	if stopCommandCount != 1 {
		t.Fatalf("expected exactly one cancel command, got %d", stopCommandCount)
	}

	if err := pool.QueryRow(ctx, `
select payload
from agent_command
where task_id = $1
  and command_type = 'cancel'
order by created_at desc
limit 1
`, taskID).Scan(&payloadBytes); err != nil {
		t.Fatalf("load cancel command payload: %v", err)
	}

	var payload commands.StopTaskCommandPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("unmarshal stop payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("unexpected stop task id: %+v", payload)
	}
	if payload.ExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("unexpected stop execution id: %+v", payload)
	}
	if payload.AgentID != "agent-runtime-1" {
		t.Fatalf("unexpected stop agent id: %+v", payload)
	}
	if payload.Reason != "cancel_requested" {
		t.Fatalf("unexpected stop reason: %+v", payload)
	}
	if payload.LeaderEpoch != lease.Epoch {
		t.Fatalf("unexpected stop leader epoch: %+v", payload)
	}
}

type fakeRuntimeCanceler struct{}

func (f *fakeRuntimeCanceler) Handle(context.Context, commands.CancelTaskCommand) (*commands.TaskRecord, error) {
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

	if imageID := strings.TrimSpace(string(output)); imageID != "" {
		return imageID
	}
	return "postgres:16-alpine"
}
