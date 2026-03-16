package repo

import (
	"context"
	"database/sql"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"
)

func TestRuntimeReposClaimLeaseAndAppendOutbox(t *testing.T) {
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

	leaseRepo := NewLeaseRepo(pool)
	lease, err := leaseRepo.AcquireOrRenew(ctx, AcquireLeaseParams{
		Name:       "runtime-scheduler",
		Holder:     "runtime-1",
		LeaseUntil: time.Now().Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("acquire lease: %v", err)
	}
	if lease.Epoch == 0 {
		t.Fatal("expected lease epoch to be assigned")
	}

	taskRepo := NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("seed runtime task: %v", err)
	}

	claimed, err := taskRepo.ClaimPendingTask(ctx, ClaimTaskParams{
		ClaimedBy:   "runtime-1",
		LeaderEpoch: lease.Epoch,
	})
	if err != nil {
		t.Fatalf("claim task: %v", err)
	}
	if claimed.ID != taskID {
		t.Fatalf("unexpected claimed task id: %s", claimed.ID)
	}

	outboxRepo := NewOutboxRepo(pool)
	entry, err := outboxRepo.Append(ctx, AppendOutboxParams{
		Topic:       "runtime.task.assigned",
		AggregateID: taskID.String(),
		Payload:     []byte(`{"task_id":"` + taskID.String() + `"}`),
	})
	if err != nil {
		t.Fatalf("append outbox: %v", err)
	}
	if entry.ID == 0 {
		t.Fatal("expected outbox id")
	}
}

func TestExecutorRepoRegisterAndHeartbeat(t *testing.T) {
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

	executorRepo := NewExecutorRepo(pool)
	registerAt := time.UnixMilli(111)
	record, err := executorRepo.Register(ctx, commands.ExecutorRecord{
		ID:           "executor-a",
		Version:      "1.2.3",
		Capabilities: []string{"gpu", "cuda"},
		LastSeenAt:   registerAt,
	})
	if err != nil {
		t.Fatalf("register executor: %v", err)
	}
	if record.ID != "executor-a" || record.Version != "1.2.3" {
		t.Fatalf("unexpected registered record: %+v", record)
	}
	if !slices.Equal(record.Capabilities, []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected registered capabilities: %+v", record.Capabilities)
	}
	if !record.LastSeenAt.Equal(registerAt) {
		t.Fatalf("unexpected registered last seen: %s", record.LastSeenAt)
	}

	heartbeatAt := registerAt.Add(time.Minute)
	if err := executorRepo.Heartbeat(ctx, "executor-a", heartbeatAt); err != nil {
		t.Fatalf("heartbeat executor: %v", err)
	}

	executors, err := executorRepo.List(ctx)
	if err != nil {
		t.Fatalf("list executors: %v", err)
	}
	if len(executors) != 1 {
		t.Fatalf("unexpected executor count: %d", len(executors))
	}
	if !executors[0].LastSeenAt.Equal(heartbeatAt) {
		t.Fatalf("unexpected heartbeat timestamp: %s", executors[0].LastSeenAt)
	}
	if !slices.Equal(executors[0].Capabilities, []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected persisted capabilities: %+v", executors[0].Capabilities)
	}
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
