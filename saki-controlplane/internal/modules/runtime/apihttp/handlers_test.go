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

	executorRepo := runtimerepo.NewExecutorRepo(pool)
	if _, err := executorRepo.Register(ctx, commands.ExecutorRecord{
		ID:           "executor-a",
		Version:      "1.2.3",
		Capabilities: []string{"gpu"},
		LastSeenAt:   time.UnixMilli(123456789),
	}); err != nil {
		t.Fatalf("register executor: %v", err)
	}

	handlers := apihttp.NewHandlers(
		apihttp.Dependencies{
			Store:    runtimequeries.NewRepoAdminStore(taskRepo, executorRepo),
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

	executors, err := handlers.ListRuntimeExecutors(ctx)
	if err != nil {
		t.Fatalf("list executors: %v", err)
	}
	if len(executors) != 1 || executors[0].ID != "executor-a" || executors[0].Version != "1.2.3" {
		t.Fatalf("unexpected executors: %+v", executors)
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
			Store: runtimequeries.NewRepoAdminStore(taskRepo, runtimerepo.NewExecutorRepo(pool)),
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

	var outboxCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from runtime_outbox
where aggregate_id = $1
  and topic = $2
`, taskID.String(), commands.StopTaskOutboxTopic).Scan(&outboxCount); err != nil {
		t.Fatalf("count stop outbox: %v", err)
	}
	if outboxCount != 0 {
		t.Fatalf("expected no stop outbox for pending cancel, got %d", outboxCount)
	}
}

func TestCancelRuntimeTaskUsesCommandPathAndWritesStopOutbox(t *testing.T) {
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
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create task: %v", err)
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

	handlers := apihttp.NewHandlers(
		apihttp.Dependencies{
			Store: runtimequeries.NewRepoAdminStore(taskRepo, runtimerepo.NewExecutorRepo(pool)),
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
