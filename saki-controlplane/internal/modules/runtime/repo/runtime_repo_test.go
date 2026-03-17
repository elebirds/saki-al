package repo

import (
	"context"
	"database/sql"
	"errors"
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

	assigned, err := taskRepo.AssignPendingTask(ctx, AssignTaskParams{
		AssignedAgentID: "agent-runtime-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}
	if assigned.ID != taskID {
		t.Fatalf("unexpected assigned task id: %s", assigned.ID)
	}
	if assigned.AssignedAgentID == nil || *assigned.AssignedAgentID != "agent-runtime-1" {
		t.Fatalf("expected assigned agent id agent-runtime-1, got %+v", assigned.AssignedAgentID)
	}

	outboxRepo := NewOutboxRepo(pool)
	entry, err := outboxRepo.Append(ctx, AppendOutboxParams{
		Topic:       "runtime.task.assign.v1",
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

	assigned, err := taskRepo.AssignPendingTask(ctx, AssignTaskParams{
		AssignedAgentID: "agent-1",
		LeaderEpoch:     lease.Epoch,
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
	if assigned.TaskKind != "PREDICTION" {
		t.Fatalf("expected assigned task kind PREDICTION, got %q", assigned.TaskKind)
	}
	if assigned.CurrentExecutionID == nil || *assigned.CurrentExecutionID == "" {
		t.Fatalf("expected assigned execution id, got %+v", assigned.CurrentExecutionID)
	}
	if assigned.AssignedAgentID == nil || *assigned.AssignedAgentID != "agent-1" {
		t.Fatalf("expected assigned agent id agent-1, got %+v", assigned.AssignedAgentID)
	}
	if assigned.Attempt != 1 {
		t.Fatalf("expected assigned attempt 1, got %d", assigned.Attempt)
	}
	if assigned.MaxAttempts != 1 {
		t.Fatalf("expected assigned max attempts 1, got %d", assigned.MaxAttempts)
	}
	if string(assigned.ResolvedParams) != "{}" {
		t.Fatalf("expected assigned resolved params {}, got %s", string(assigned.ResolvedParams))
	}
	if len(assigned.DependsOnTaskIDs) != 0 {
		t.Fatalf("expected assigned dependencies to be empty, got %+v", assigned.DependsOnTaskIDs)
	}
	if assigned.LeaderEpoch == nil || *assigned.LeaderEpoch != lease.Epoch {
		t.Fatalf("expected assigned leader epoch %d, got %+v", lease.Epoch, assigned.LeaderEpoch)
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
	if *assigned.CurrentExecutionID != currentExecutionID {
		t.Fatalf("expected repo result execution id %q, got %q", currentExecutionID, *assigned.CurrentExecutionID)
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

func TestRuntimeCoreAlignmentMigrationKeepsLegacyClaimedByUnmapped(t *testing.T) {
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
	migrationsDir := runtimeMigrationsDir(t)
	if err := goose.UpTo(sqlDB, migrationsDir, 30); err != nil {
		t.Fatalf("run migrations to 30: %v", err)
	}

	taskID := uuid.New()
	if _, err := sqlDB.ExecContext(ctx, `
insert into runtime_task (id, task_type, status, claimed_by, claimed_at, leader_epoch)
values ($1, 'predict', 'dispatching', 'runtime-holder-1', now(), 7)
`, taskID); err != nil {
		t.Fatalf("insert legacy runtime task: %v", err)
	}

	if err := goose.UpTo(sqlDB, migrationsDir, 31); err != nil {
		t.Fatalf("run migrations to 31: %v", err)
	}

	var (
		status             string
		legacyClaimedBy    sql.NullString
		assignedAgentID    sql.NullString
		currentExecutionID sql.NullString
	)
	if err := sqlDB.QueryRowContext(ctx, `
select status, claimed_by, assigned_agent_id, current_execution_id
from runtime_task
where id = $1
`, taskID).Scan(&status, &legacyClaimedBy, &assignedAgentID, &currentExecutionID); err != nil {
		t.Fatalf("load aligned runtime task: %v", err)
	}

	if status != "assigned" {
		t.Fatalf("expected migrated status assigned, got %q", status)
	}
	if !legacyClaimedBy.Valid || legacyClaimedBy.String != "runtime-holder-1" {
		t.Fatalf("expected legacy claimed_by to be preserved, got %+v", legacyClaimedBy)
	}
	if assignedAgentID.Valid {
		t.Fatalf("expected assigned_agent_id to stay null for legacy row, got %q", assignedAgentID.String)
	}
	if !currentExecutionID.Valid || currentExecutionID.String == "" {
		t.Fatalf("expected current_execution_id to be backfilled, got %+v", currentExecutionID)
	}
}

func TestRuntimeCoreAlignmentMigrationDownIsForwardOnly(t *testing.T) {
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
	migrationsDir := runtimeMigrationsDir(t)
	if err := goose.UpTo(sqlDB, migrationsDir, 31); err != nil {
		t.Fatalf("run migrations to 31: %v", err)
	}

	err = goose.DownTo(sqlDB, migrationsDir, 30)
	if err == nil {
		t.Fatal("expected 000031 down migration to refuse rollback")
	}
	if !strings.Contains(err.Error(), "forward-only") {
		t.Fatalf("expected forward-only rollback error, got %v", err)
	}
}

func TestOutboxRepoDefaultsIdempotencyKeyWithPayloadSpecificity(t *testing.T) {
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
	aggregateID := uuid.NewString()
	entryA, err := outboxRepo.Append(ctx, AppendOutboxParams{
		Topic:       "runtime.task.assign.v1",
		AggregateID: aggregateID,
		Payload:     []byte(`{"task_id":"` + aggregateID + `","execution_id":"exec-a"}`),
	})
	if err != nil {
		t.Fatalf("append outbox a: %v", err)
	}
	entryB, err := outboxRepo.Append(ctx, AppendOutboxParams{
		Topic:       "runtime.task.assign.v1",
		AggregateID: aggregateID,
		Payload:     []byte(`{"task_id":"` + aggregateID + `","execution_id":"exec-b"}`),
	})
	if err != nil {
		t.Fatalf("append outbox b: %v", err)
	}

	if entryA.IdempotencyKey == "" || entryB.IdempotencyKey == "" {
		t.Fatalf("expected idempotency keys, got a=%q b=%q", entryA.IdempotencyKey, entryB.IdempotencyKey)
	}
	if entryA.IdempotencyKey == entryB.IdempotencyKey {
		t.Fatalf("expected payload-specific idempotency keys, got identical %q", entryA.IdempotencyKey)
	}

	explicit, err := outboxRepo.Append(ctx, AppendOutboxParams{
		Topic:          "runtime.task.assign.v1",
		AggregateID:    aggregateID,
		IdempotencyKey: "runtime.task.assign.v1:logical-effect:1",
		Payload:        []byte(`{"task_id":"` + aggregateID + `","execution_id":"exec-explicit"}`),
	})
	if err != nil {
		t.Fatalf("append outbox explicit: %v", err)
	}
	if explicit.IdempotencyKey != "runtime.task.assign.v1:logical-effect:1" {
		t.Fatalf("expected explicit idempotency key to be preserved, got %q", explicit.IdempotencyKey)
	}
}

func TestOutboxRepoRejectsStaleClaimMarks(t *testing.T) {
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

	worker1ClaimUntil := time.Now().Add(40 * time.Millisecond)
	worker1Claim, err := outboxRepo.ClaimDue(ctx, 1, worker1ClaimUntil)
	if err != nil {
		t.Fatalf("worker1 claim due: %v", err)
	}
	if len(worker1Claim) != 1 || worker1Claim[0].ID != entry.ID {
		t.Fatalf("unexpected worker1 claim: %+v", worker1Claim)
	}

	time.Sleep(80 * time.Millisecond)

	worker2ClaimUntil := time.Now().Add(2 * time.Minute)
	worker2Claim, err := outboxRepo.ClaimDue(ctx, 1, worker2ClaimUntil)
	if err != nil {
		t.Fatalf("worker2 claim due: %v", err)
	}
	if len(worker2Claim) != 1 || worker2Claim[0].ID != entry.ID {
		t.Fatalf("unexpected worker2 claim: %+v", worker2Claim)
	}

	staleRetryAt := time.Now().Add(time.Minute)
	err = outboxRepo.MarkRetry(ctx, entry.ID, worker1Claim[0].AvailableAt, staleRetryAt, "temporary failure")
	if !errors.Is(err, ErrOutboxClaimExpired) {
		t.Fatalf("expected stale retry to fail with ErrOutboxClaimExpired, got %v", err)
	}

	err = outboxRepo.MarkPublished(ctx, entry.ID, worker1Claim[0].AvailableAt)
	if !errors.Is(err, ErrOutboxClaimExpired) {
		t.Fatalf("expected stale publish to fail with ErrOutboxClaimExpired, got %v", err)
	}

	retryAt := time.Now().Add(-time.Second)
	if err := outboxRepo.MarkRetry(ctx, entry.ID, worker2Claim[0].AvailableAt, retryAt, "temporary failure"); err != nil {
		t.Fatalf("mark current claim retry: %v", err)
	}

	var (
		availableAt  time.Time
		attemptCount int32
		lastError    sql.NullString
	)
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
	if attemptCount != 2 {
		t.Fatalf("expected attempt count to remain 2 after retry mark, got %d", attemptCount)
	}
	if !lastError.Valid || lastError.String != "temporary failure" {
		t.Fatalf("expected retry error to be stored, got %+v", lastError)
	}

	reclaimed, err := outboxRepo.ClaimDue(ctx, 1, time.Now().Add(4*time.Minute))
	if err != nil {
		t.Fatalf("reclaim due outbox: %v", err)
	}
	if len(reclaimed) != 1 || reclaimed[0].ID != entry.ID {
		t.Fatalf("unexpected reclaimed entries: %+v", reclaimed)
	}

	if err := outboxRepo.MarkPublished(ctx, entry.ID, reclaimed[0].AvailableAt); err != nil {
		t.Fatalf("mark outbox published: %v", err)
	}

	var publishedAt sql.NullTime
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
	if attemptCount != 3 {
		t.Fatalf("expected third claim to increment attempt count to 3, got %d", attemptCount)
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
