package repo

import (
	"context"
	"database/sql"
	"os/exec"
	"path/filepath"
	"reflect"
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

func TestTaskRepoAssignsExecutionAndAgent(t *testing.T) {
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

	taskRepo := NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create task: %v", err)
	}

	assigned, err := taskRepo.ClaimPendingTask(ctx, ClaimTaskParams{
		ClaimedBy:   "agent-1",
		LeaderEpoch: lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign pending task: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
	}
	if assigned.Status != "assigned" {
		t.Fatalf("expected assigned status, got %q", assigned.Status)
	}

	var (
		taskKind           string
		currentExecutionID string
		assignedAgentID    string
		attempt            int32
		maxAttempts        int32
		resolvedParams     string
		dependsOnTaskIDs   string
		leaderEpoch        int64
	)
	err = pool.QueryRow(ctx, `
select
	task_kind,
	current_execution_id,
	assigned_agent_id,
	attempt,
	max_attempts,
	resolved_params::text,
	coalesce(array_to_json(depends_on_task_ids)::text, '[]'),
	leader_epoch
from runtime_task
where id = $1
`, taskID).Scan(
		&taskKind,
		&currentExecutionID,
		&assignedAgentID,
		&attempt,
		&maxAttempts,
		&resolvedParams,
		&dependsOnTaskIDs,
		&leaderEpoch,
	)
	if err != nil {
		t.Fatalf("load aligned runtime task: %v", err)
	}

	if taskKind == "" {
		t.Fatal("expected task kind to be persisted")
	}
	if currentExecutionID == "" {
		t.Fatal("expected current execution id to be generated")
	}
	if assignedAgentID != "agent-1" {
		t.Fatalf("expected assigned agent id agent-1, got %q", assignedAgentID)
	}
	if attempt != 1 {
		t.Fatalf("expected attempt 1, got %d", attempt)
	}
	if maxAttempts != 1 {
		t.Fatalf("expected max attempts 1, got %d", maxAttempts)
	}
	if resolvedParams != "{}" {
		t.Fatalf("expected empty resolved params, got %s", resolvedParams)
	}
	if dependsOnTaskIDs != "[]" {
		t.Fatalf("expected empty dependency list, got %s", dependsOnTaskIDs)
	}
	if leaderEpoch != lease.Epoch {
		t.Fatalf("expected leader epoch %d, got %d", lease.Epoch, leaderEpoch)
	}
}

func TestOutboxRepoClaimsAndMarksPublished(t *testing.T) {
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

	outboxRepo := NewOutboxRepo(pool)
	entry, err := outboxRepo.Append(ctx, AppendOutboxParams{
		Topic:       "runtime.task.assign.v1",
		AggregateID: uuid.NewString(),
		Payload:     []byte(`{"task_id":"` + uuid.NewString() + `"}`),
	})
	if err != nil {
		t.Fatalf("append outbox: %v", err)
	}

	var (
		aggregateType  string
		idempotencyKey string
		availableAt    time.Time
		attemptCount   int32
		publishedAt    sql.NullTime
		lastError      sql.NullString
	)
	err = pool.QueryRow(ctx, `
select aggregate_type, idempotency_key, available_at, attempt_count, published_at, last_error
from runtime_outbox
where id = $1
`, entry.ID).Scan(
		&aggregateType,
		&idempotencyKey,
		&availableAt,
		&attemptCount,
		&publishedAt,
		&lastError,
	)
	if err != nil {
		t.Fatalf("load aligned outbox: %v", err)
	}

	if aggregateType == "" {
		t.Fatal("expected aggregate type to be persisted")
	}
	if idempotencyKey == "" {
		t.Fatal("expected idempotency key to be persisted")
	}
	if availableAt.IsZero() {
		t.Fatal("expected available_at to be set")
	}
	if attemptCount != 0 {
		t.Fatalf("expected attempt count 0, got %d", attemptCount)
	}
	if publishedAt.Valid {
		t.Fatalf("expected unpublished entry, got %v", publishedAt.Time)
	}
	if lastError.Valid {
		t.Fatalf("expected empty last error, got %q", lastError.String)
	}

	claimUntil := time.Now().Add(2 * time.Minute)
	claimed := callOutboxClaimDue(t, outboxRepo, ctx, 1, claimUntil)
	if len(claimed) != 1 || claimed[0].ID != entry.ID {
		t.Fatalf("unexpected claimed entries: %+v", claimed)
	}

	if got := callOutboxClaimDue(t, outboxRepo, ctx, 1, time.Now().Add(3*time.Minute)); len(got) != 0 {
		t.Fatalf("expected claimed entry to be fenced by available_at, got %+v", got)
	}

	retryAt := time.Now().Add(-time.Second)
	callOutboxMarkRetry(t, outboxRepo, ctx, entry.ID, retryAt, "temporary failure")

	err = pool.QueryRow(ctx, `
select available_at, attempt_count, last_error
from runtime_outbox
where id = $1
`, entry.ID).Scan(&availableAt, &attemptCount, &lastError)
	if err != nil {
		t.Fatalf("load retried outbox: %v", err)
	}
	if availableAt.After(time.Now()) {
		t.Fatalf("expected retry entry to be immediately available, got %s", availableAt)
	}
	if attemptCount != 1 {
		t.Fatalf("expected attempt count to remain 1 after retry mark, got %d", attemptCount)
	}
	if !lastError.Valid || lastError.String != "temporary failure" {
		t.Fatalf("expected retry error to be stored, got %+v", lastError)
	}

	reclaimed := callOutboxClaimDue(t, outboxRepo, ctx, 1, time.Now().Add(4*time.Minute))
	if len(reclaimed) != 1 || reclaimed[0].ID != entry.ID {
		t.Fatalf("unexpected reclaimed entries: %+v", reclaimed)
	}

	callOutboxMarkPublished(t, outboxRepo, ctx, entry.ID)

	err = pool.QueryRow(ctx, `
select published_at, last_error, attempt_count
from runtime_outbox
where id = $1
`, entry.ID).Scan(&publishedAt, &lastError, &attemptCount)
	if err != nil {
		t.Fatalf("load published outbox: %v", err)
	}
	if !publishedAt.Valid {
		t.Fatal("expected published_at to be set")
	}
	if lastError.Valid {
		t.Fatalf("expected last_error to be cleared, got %q", lastError.String)
	}
	if attemptCount != 2 {
		t.Fatalf("expected second claim to increment attempt count to 2, got %d", attemptCount)
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

func callOutboxClaimDue(t *testing.T, repo *OutboxRepo, ctx context.Context, limit int32, claimUntil time.Time) []OutboxEntry {
	t.Helper()

	method := reflect.ValueOf(repo).MethodByName("ClaimDue")
	if !method.IsValid() {
		t.Fatal("expected OutboxRepo.ClaimDue to exist")
	}

	results := method.Call([]reflect.Value{
		reflect.ValueOf(ctx),
		reflect.ValueOf(limit),
		reflect.ValueOf(claimUntil),
	})
	if len(results) != 2 {
		t.Fatalf("unexpected ClaimDue result count: %d", len(results))
	}
	if err, _ := results[1].Interface().(error); err != nil {
		t.Fatalf("claim due outbox: %v", err)
	}
	entries, ok := results[0].Interface().([]OutboxEntry)
	if !ok {
		t.Fatalf("unexpected ClaimDue return type: %T", results[0].Interface())
	}
	return entries
}

func callOutboxMarkRetry(t *testing.T, repo *OutboxRepo, ctx context.Context, id int64, nextAvailableAt time.Time, lastError string) {
	t.Helper()

	method := reflect.ValueOf(repo).MethodByName("MarkRetry")
	if !method.IsValid() {
		t.Fatal("expected OutboxRepo.MarkRetry to exist")
	}

	results := method.Call([]reflect.Value{
		reflect.ValueOf(ctx),
		reflect.ValueOf(id),
		reflect.ValueOf(nextAvailableAt),
		reflect.ValueOf(lastError),
	})
	if len(results) != 1 {
		t.Fatalf("unexpected MarkRetry result count: %d", len(results))
	}
	if err, _ := results[0].Interface().(error); err != nil {
		t.Fatalf("mark outbox retry: %v", err)
	}
}

func callOutboxMarkPublished(t *testing.T, repo *OutboxRepo, ctx context.Context, id int64) {
	t.Helper()

	method := reflect.ValueOf(repo).MethodByName("MarkPublished")
	if !method.IsValid() {
		t.Fatal("expected OutboxRepo.MarkPublished to exist")
	}

	results := method.Call([]reflect.Value{
		reflect.ValueOf(ctx),
		reflect.ValueOf(id),
	})
	if len(results) != 1 {
		t.Fatalf("unexpected MarkPublished result count: %d", len(results))
	}
	if err, _ := results[0].Interface().(error); err != nil {
		t.Fatalf("mark outbox published: %v", err)
	}
}
