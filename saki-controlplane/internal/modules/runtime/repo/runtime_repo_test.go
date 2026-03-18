package repo

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
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
	if assigned.AssignedAgentID != "agent-runtime-1" {
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
	if assigned.CurrentExecutionID == "" {
		t.Fatalf("expected assigned execution id, got %+v", assigned.CurrentExecutionID)
	}
	if assigned.AssignedAgentID != "agent-1" {
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
	if assigned.LeaderEpoch != lease.Epoch {
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
	if assigned.CurrentExecutionID != currentExecutionID {
		t.Fatalf("expected repo result execution id %q, got %q", currentExecutionID, assigned.CurrentExecutionID)
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

func TestTaskRepoAdvanceTaskByExecutionUpdatesMatchingExecutionAndStatus(t *testing.T) {
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
		AssignedAgentID: "agent-start-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}

	advanced, err := taskRepo.AdvanceTaskByExecution(ctx, commands.AdvanceTaskByExecutionParams{
		ID:           taskID,
		ExecutionID:  assigned.CurrentExecutionID,
		FromStatuses: []string{"assigned"},
		ToStatus:     "running",
	})
	if err != nil {
		t.Fatalf("advance task by execution: %v", err)
	}
	if advanced == nil || advanced.Status != "running" {
		t.Fatalf("expected running task, got %+v", advanced)
	}

	persisted, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("get task: %v", err)
	}
	if persisted == nil || persisted.Status != "running" {
		t.Fatalf("expected persisted running task, got %+v", persisted)
	}
}

func TestTaskRepoAdvanceTaskByExecutionLeavesTaskUnchangedWhenStatusDrifts(t *testing.T) {
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
		AssignedAgentID: "agent-start-rollback-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}

	if err := taskRepo.UpdateTask(ctx, commands.TaskUpdate{
		ID:              taskID,
		Status:          "cancel_requested",
		AssignedAgentID: assigned.AssignedAgentID,
		LeaderEpoch:     lease.Epoch,
	}); err != nil {
		t.Fatalf("prepare status drift: %v", err)
	}

	advanced, err := taskRepo.AdvanceTaskByExecution(ctx, commands.AdvanceTaskByExecutionParams{
		ID:           taskID,
		ExecutionID:  assigned.CurrentExecutionID,
		FromStatuses: []string{"assigned"},
		ToStatus:     "running",
	})
	if err != nil {
		t.Fatalf("advance task by execution after drift: %v", err)
	}
	if advanced != nil {
		t.Fatalf("expected no update after status drift, got %+v", advanced)
	}

	persisted, err := taskRepo.GetTask(ctx, taskID)
	if err != nil {
		t.Fatalf("get task: %v", err)
	}
	if persisted == nil || persisted.Status != "cancel_requested" {
		t.Fatalf("expected cancel_requested task to be preserved, got %+v", persisted)
	}
}

func TestAssignTaskHandlerUsesTaskRepoClaimAndAppendsFrozenOutbox(t *testing.T) {
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

	handler := commands.NewAssignTaskHandlerWithTx(NewAssignTaskTxRunner(pool))
	assigned, err := handler.Handle(ctx, commands.AssignTaskCommand{
		AssignedAgentID: "agent-handler-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
	}
	if assigned.ID != taskID {
		t.Fatalf("expected task id %s, got %s", taskID, assigned.ID)
	}
	if assigned.CurrentExecutionID == "" {
		t.Fatal("expected execution id to be populated")
	}
	if assigned.AssignedAgentID != "agent-handler-1" {
		t.Fatalf("expected assigned agent id agent-handler-1, got %q", assigned.AssignedAgentID)
	}
	if assigned.LeaderEpoch != lease.Epoch {
		t.Fatalf("expected leader epoch %d, got %d", lease.Epoch, assigned.LeaderEpoch)
	}

	var (
		topic          string
		idempotencyKey string
		payloadBytes   []byte
	)
	if err := pool.QueryRow(ctx, `
select topic, idempotency_key, payload
from runtime_outbox
where aggregate_id = $1
`, taskID.String()).Scan(&topic, &idempotencyKey, &payloadBytes); err != nil {
		t.Fatalf("load runtime outbox: %v", err)
	}
	if topic != commands.AssignTaskOutboxTopic {
		t.Fatalf("expected topic %s, got %q", commands.AssignTaskOutboxTopic, topic)
	}
	if idempotencyKey != commands.AssignTaskOutboxTopic+":"+assigned.CurrentExecutionID {
		t.Fatalf("expected execution-scoped idempotency key, got %q", idempotencyKey)
	}

	var payload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("expected payload task id %s, got %s", taskID, payload.TaskID)
	}
	if payload.ExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("expected payload execution id %q, got %q", assigned.CurrentExecutionID, payload.ExecutionID)
	}
	if payload.AgentID != "agent-handler-1" {
		t.Fatalf("expected payload agent id agent-handler-1, got %q", payload.AgentID)
	}
	if payload.TaskKind != "PREDICTION" || payload.TaskType != "predict" {
		t.Fatalf("unexpected payload task metadata: %+v", payload)
	}
	if payload.Attempt != 1 || payload.MaxAttempts != 1 {
		t.Fatalf("unexpected payload attempts: %+v", payload)
	}
	if string(payload.ResolvedParams) != "{}" {
		t.Fatalf("expected payload resolved params {}, got %s", string(payload.ResolvedParams))
	}
	if len(payload.DependsOnTaskIDs) != 0 {
		t.Fatalf("expected empty dependency ids, got %+v", payload.DependsOnTaskIDs)
	}
	if payload.LeaderEpoch != lease.Epoch {
		t.Fatalf("expected payload leader epoch %d, got %d", lease.Epoch, payload.LeaderEpoch)
	}
}

func TestAssignTaskHandlerWithTxReturnsNilWhenTaskRepoHasNoPendingTask(t *testing.T) {
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

	handler := commands.NewAssignTaskHandlerWithTx(NewAssignTaskTxRunner(pool))
	assigned, err := handler.Handle(ctx, commands.AssignTaskCommand{
		AssignedAgentID: "agent-empty-queue",
		LeaderEpoch:     1,
	})
	if err != nil {
		t.Fatalf("expected empty queue to be non-error, got %v", err)
	}
	if assigned != nil {
		t.Fatalf("expected nil assigned task on empty queue, got %+v", assigned)
	}

	outboxRepo := NewOutboxRepo(pool)
	entries, err := outboxRepo.ClaimDue(ctx, 1, time.Now().Add(time.Minute))
	if err != nil {
		t.Fatalf("claim due outbox: %v", err)
	}
	if len(entries) != 0 {
		t.Fatalf("expected no outbox entries on empty queue, got %+v", entries)
	}
}

func TestAssignTaskHandlerWithTxRollsBackClaimWhenOutboxAppendFails(t *testing.T) {
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

	taskRepo := NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create task: %v", err)
	}

	handler := commands.NewAssignTaskHandlerWithTx(newFailingAssignTaskTxRunner(pool))
	assigned, err := handler.Handle(ctx, commands.AssignTaskCommand{
		AssignedAgentID: "agent-rollback-1",
		LeaderEpoch:     9,
	})
	if err == nil {
		t.Fatal("expected append failure")
	}
	if assigned != nil {
		t.Fatalf("expected nil task when append fails, got %+v", assigned)
	}

	var (
		status             string
		currentExecutionID sql.NullString
		assignedAgentID    sql.NullString
	)
	if err := pool.QueryRow(ctx, `
select status, current_execution_id, assigned_agent_id
from runtime_task
where id = $1
`, taskID).Scan(&status, &currentExecutionID, &assignedAgentID); err != nil {
		t.Fatalf("load runtime task: %v", err)
	}
	if status != "pending" {
		t.Fatalf("expected pending status after rollback, got %q", status)
	}
	if currentExecutionID.Valid {
		t.Fatalf("expected current_execution_id rollback, got %+v", currentExecutionID)
	}
	if assignedAgentID.Valid {
		t.Fatalf("expected assigned_agent_id rollback, got %+v", assignedAgentID)
	}
}

func TestCancelTaskHandlerWritesFrozenStopOutboxForAssignedTask(t *testing.T) {
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
		AssignedAgentID: "agent-cancel-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}

	handler := commands.NewCancelTaskHandlerWithTx(NewCancelTaskTxRunner(pool))
	canceled, err := handler.Handle(ctx, commands.CancelTaskCommand{TaskID: taskID})
	if err != nil {
		t.Fatalf("cancel task: %v", err)
	}
	if canceled == nil || canceled.Status != "cancel_requested" {
		t.Fatalf("expected cancel_requested result, got %+v", canceled)
	}

	var payloadBytes []byte
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
		t.Fatalf("expected task id %s, got %s", taskID, payload.TaskID)
	}
	if payload.ExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("expected execution id %q, got %q", assigned.CurrentExecutionID, payload.ExecutionID)
	}
	if payload.AgentID != "agent-cancel-1" {
		t.Fatalf("expected agent id agent-cancel-1, got %q", payload.AgentID)
	}
	if payload.Reason != "cancel_requested" {
		t.Fatalf("expected reason cancel_requested, got %q", payload.Reason)
	}
	if payload.LeaderEpoch != lease.Epoch {
		t.Fatalf("expected leader epoch %d, got %d", lease.Epoch, payload.LeaderEpoch)
	}
}

func TestCancelTaskHandlerLeavesAssignedTaskUnchangedWhenStopOutboxAppendFails(t *testing.T) {
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
		AssignedAgentID: "agent-cancel-rollback-1",
		LeaderEpoch:     lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task: %v", err)
	}

	handler := commands.NewCancelTaskHandlerWithTx(newFailingCancelTaskTxRunner(pool))
	canceled, err := handler.Handle(ctx, commands.CancelTaskCommand{TaskID: taskID})
	if err == nil {
		t.Fatal("expected stop outbox append failure")
	}
	if canceled != nil {
		t.Fatalf("expected nil task when append fails, got %+v", canceled)
	}

	var (
		status             string
		currentExecutionID string
		assignedAgentID    string
	)
	if err := pool.QueryRow(ctx, `
select status, current_execution_id, assigned_agent_id
from runtime_task
where id = $1
`, taskID).Scan(&status, &currentExecutionID, &assignedAgentID); err != nil {
		t.Fatalf("load runtime task: %v", err)
	}
	if status != "assigned" {
		t.Fatalf("expected assigned status after rollback, got %q", status)
	}
	if currentExecutionID != assigned.CurrentExecutionID {
		t.Fatalf("expected execution id %q to be preserved, got %q", assigned.CurrentExecutionID, currentExecutionID)
	}
	if assignedAgentID != "agent-cancel-rollback-1" {
		t.Fatalf("expected assigned agent id agent-cancel-rollback-1, got %q", assignedAgentID)
	}
}

func TestRuntimeBaseMigrationIncludesAlignedTaskColumns(t *testing.T) {
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
insert into runtime_task (id, task_type)
values ($1, 'predict')
`, taskID); err != nil {
		t.Fatalf("insert aligned runtime task: %v", err)
	}

	var (
		taskKind           string
		status             string
		assignedAgentID    sql.NullString
		currentExecutionID sql.NullString
		attempt            int32
		maxAttempts        int32
		resolvedParams     string
		dependsOnTaskIDs   string
	)
	if err := sqlDB.QueryRowContext(ctx, `
select task_kind::text, status::text, assigned_agent_id, current_execution_id, attempt, max_attempts, resolved_params::text, coalesce(array_to_json(depends_on_task_ids)::text, '[]')
from runtime_task
where id = $1
`, taskID).Scan(&taskKind, &status, &assignedAgentID, &currentExecutionID, &attempt, &maxAttempts, &resolvedParams, &dependsOnTaskIDs); err != nil {
		t.Fatalf("load runtime task defaults: %v", err)
	}

	if taskKind != "PREDICTION" {
		t.Fatalf("expected default task kind PREDICTION, got %q", taskKind)
	}
	if status != "pending" {
		t.Fatalf("expected default status pending, got %q", status)
	}
	if assignedAgentID.Valid {
		t.Fatalf("expected assigned_agent_id to default null, got %q", assignedAgentID.String)
	}
	if currentExecutionID.Valid {
		t.Fatalf("expected current_execution_id to default null, got %+v", currentExecutionID)
	}
	if attempt != 0 || maxAttempts != 1 {
		t.Fatalf("unexpected attempt defaults: attempt=%d max_attempts=%d", attempt, maxAttempts)
	}
	if resolvedParams != "{}" {
		t.Fatalf("expected default resolved_params {}, got %s", resolvedParams)
	}
	if dependsOnTaskIDs != "[]" {
		t.Fatalf("expected default depends_on_task_ids [], got %s", dependsOnTaskIDs)
	}

	var claimedByExists bool
	if err := sqlDB.QueryRowContext(ctx, `
select exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'runtime_task'
      and column_name = 'claimed_by'
)
`).Scan(&claimedByExists); err != nil {
		t.Fatalf("query runtime_task columns: %v", err)
	}
	if claimedByExists {
		t.Fatal("expected claimed_by to be absent after history rewrite")
	}
}

func TestRuntimeCoreAlignmentMigrationIsNoopAfterHistoryRewrite(t *testing.T) {
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

	taskID := uuid.New()
	if _, err := sqlDB.ExecContext(ctx, `
insert into runtime_task (id, task_type, task_kind, status, assigned_agent_id, current_execution_id, leader_epoch)
values ($1, 'predict', 'PREDICTION', 'assigned', 'agent-1', 'exec-1', 7)
`, taskID); err != nil {
		t.Fatalf("insert runtime task at version 31: %v", err)
	}

	if err := goose.DownTo(sqlDB, migrationsDir, 30); err != nil {
		t.Fatalf("down to 30 after no-op 31: %v", err)
	}

	version, err := goose.GetDBVersion(sqlDB)
	if err != nil {
		t.Fatalf("get db version: %v", err)
	}
	if version != 30 {
		t.Fatalf("expected db version 30 after down, got %d", version)
	}

	var (
		taskKind        string
		status          string
		assignedAgentID string
		executionID     string
	)
	if err := sqlDB.QueryRowContext(ctx, `
select task_kind::text, status::text, assigned_agent_id, current_execution_id
from runtime_task
where id = $1
`, taskID).Scan(&taskKind, &status, &assignedAgentID, &executionID); err != nil {
		t.Fatalf("load runtime task after down to 30: %v", err)
	}
	if taskKind != "PREDICTION" || status != "assigned" {
		t.Fatalf("expected runtime task row to survive no-op rollback, got task_kind=%q status=%q", taskKind, status)
	}
	if assignedAgentID != "agent-1" || executionID != "exec-1" {
		t.Fatalf("unexpected runtime task payload after rollback: assigned_agent_id=%q execution_id=%q", assignedAgentID, executionID)
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

type failingAssignTaskTxRunner struct {
	tx *appdb.TxRunner
}

func newFailingAssignTaskTxRunner(pool *pgxpool.Pool) *failingAssignTaskTxRunner {
	return &failingAssignTaskTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *failingAssignTaskTxRunner) InTx(ctx context.Context, fn func(store commands.AssignTaskTx) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		return fn(failingAssignTaskTxStore{
			tasks: newTaskRepo(sqlcdb.New(tx)),
		})
	})
}

type failingAssignTaskTxStore struct {
	tasks *TaskRepo
}

func (s failingAssignTaskTxStore) AssignPendingTask(ctx context.Context, params commands.AssignClaimParams) (*commands.ClaimedTask, error) {
	return s.tasks.AssignPendingTask(ctx, params)
}

func (failingAssignTaskTxStore) Append(context.Context, commands.OutboxEvent) error {
	return errors.New("append failed")
}

type failingCancelTaskTxRunner struct {
	tx *appdb.TxRunner
}

func newFailingCancelTaskTxRunner(pool *pgxpool.Pool) *failingCancelTaskTxRunner {
	return &failingCancelTaskTxRunner{tx: appdb.NewTxRunner(pool)}
}

func (r *failingCancelTaskTxRunner) InTx(ctx context.Context, fn func(store commands.CancelTaskStore) error) error {
	return r.tx.InTx(ctx, func(tx pgx.Tx) error {
		return fn(failingCancelTaskTxStore{
			tasks: newTaskRepo(sqlcdb.New(tx)),
		})
	})
}

type failingCancelTaskTxStore struct {
	tasks *TaskRepo
}

func (s failingCancelTaskTxStore) GetTask(ctx context.Context, taskID uuid.UUID) (*commands.TaskRecord, error) {
	return s.tasks.GetTask(ctx, taskID)
}

func (s failingCancelTaskTxStore) UpdateTask(ctx context.Context, update commands.TaskUpdate) error {
	return s.tasks.UpdateTask(ctx, update)
}

func (failingCancelTaskTxStore) Append(context.Context, commands.OutboxEvent) error {
	return errors.New("append failed")
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
