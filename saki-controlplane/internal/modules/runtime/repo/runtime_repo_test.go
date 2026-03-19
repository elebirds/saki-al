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

func TestRuntimeReposClaimLeaseAndAppendAgentCommand(t *testing.T) {
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

	agentRepo := NewAgentRepo(pool)
	if _, err := agentRepo.Upsert(ctx, UpsertAgentParams{
		ID:             "agent-runtime-1",
		Version:        "test",
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     time.Now().UTC(),
	}); err != nil {
		t.Fatalf("upsert agent: %v", err)
	}

	assignmentRepo := NewTaskAssignmentRepo(pool)
	assignment, err := assignmentRepo.Create(ctx, CreateTaskAssignmentParams{
		TaskID:      taskID,
		Attempt:     1,
		AgentID:     "agent-runtime-1",
		ExecutionID: assigned.CurrentExecutionID,
		Status:      "assigned",
	})
	if err != nil {
		t.Fatalf("create assignment: %v", err)
	}

	commandRepo := NewAgentCommandRepo(pool)
	entry, err := commandRepo.AppendAssign(ctx, AppendAssignCommandParams{
		CommandID:     uuid.New(),
		AgentID:       "agent-runtime-1",
		TaskID:        taskID,
		AssignmentID:  assignment.ID,
		TransportMode: "pull",
		Payload:       []byte(`{"task_id":"` + taskID.String() + `"}`),
		AvailableAt:   time.Now().UTC(),
		ExpireAt:      time.Now().Add(time.Minute).UTC(),
	})
	if err != nil {
		t.Fatalf("append agent command: %v", err)
	}
	if entry.CommandID == uuid.Nil || entry.Status != "pending" {
		t.Fatalf("expected pending command append, got %+v", entry)
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

func TestAssignTaskHandlerUsesTaskRepoClaimAndPersistsAgentCommand(t *testing.T) {
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

	seedAssignableAgent(t, ctx, pool, "agent-handler-1", []string{})

	handler := commands.NewAssignTaskHandlerWithTx(NewAssignTaskTxRunner(pool), pickFirstAgentSelector{})
	assigned, err := handler.Handle(ctx, commands.AssignTaskCommand{
		LeaderEpoch: lease.Epoch,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
	}
	if assigned.TaskID != taskID {
		t.Fatalf("expected task id %s, got %s", taskID, assigned.TaskID)
	}
	if assigned.ExecutionID == "" {
		t.Fatal("expected execution id to be populated")
	}
	if assigned.AgentID != "agent-handler-1" {
		t.Fatalf("expected assigned agent id agent-handler-1, got %q", assigned.AgentID)
	}
	if assigned.AssignmentID == 0 {
		t.Fatalf("expected assignment id, got %+v", assigned)
	}

	var payloadBytes []byte
	if err := pool.QueryRow(ctx, `
select payload
from agent_command
where task_id = $1
  and command_type = 'assign'
order by created_at desc
limit 1
`, taskID).Scan(&payloadBytes); err != nil {
		t.Fatalf("load agent command payload: %v", err)
	}

	var payload commands.AssignTaskCommandPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("expected payload task id %s, got %s", taskID, payload.TaskID)
	}
	if payload.ExecutionID != assigned.ExecutionID {
		t.Fatalf("expected payload execution id %q, got %q", assigned.ExecutionID, payload.ExecutionID)
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

	var (
		assignmentAgentID    string
		assignmentExecution  string
		commandTransportMode string
	)
	if err := pool.QueryRow(ctx, `
select a.agent_id, a.execution_id, c.transport_mode
from task_assignment a
join agent_command c on c.assignment_id = a.id
where a.task_id = $1
`, taskID).Scan(&assignmentAgentID, &assignmentExecution, &commandTransportMode); err != nil {
		t.Fatalf("load assignment/command state: %v", err)
	}
	if assignmentAgentID != "agent-handler-1" || assignmentExecution != assigned.ExecutionID {
		t.Fatalf("unexpected assignment state agent=%q execution=%q", assignmentAgentID, assignmentExecution)
	}
	if commandTransportMode != "pull" {
		t.Fatalf("expected assign command transport pull, got %q", commandTransportMode)
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

	handler := commands.NewAssignTaskHandlerWithTx(NewAssignTaskTxRunner(pool), pickFirstAgentSelector{})
	assigned, err := handler.Handle(ctx, commands.AssignTaskCommand{
		LeaderEpoch: 1,
	})
	if err != nil {
		t.Fatalf("expected empty queue to be non-error, got %v", err)
	}
	if assigned != nil {
		t.Fatalf("expected nil assigned task on empty queue, got %+v", assigned)
	}

	var commandCount int
	if err := pool.QueryRow(ctx, `
select count(*)
from agent_command
`).Scan(&commandCount); err != nil {
		t.Fatalf("count agent commands: %v", err)
	}
	if commandCount != 0 {
		t.Fatalf("expected no commands on empty queue, got %d", commandCount)
	}
}

func TestAssignTaskHandlerWithTxRollsBackClaimWhenCommandAppendFails(t *testing.T) {
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

	seedAssignableAgent(t, ctx, pool, "agent-rollback-1", []string{})

	handler := commands.NewAssignTaskHandlerWithTx(newFailingAssignTaskTxRunner(pool), pickFirstAgentSelector{})
	assigned, err := handler.Handle(ctx, commands.AssignTaskCommand{
		LeaderEpoch: 9,
	})
	if err == nil {
		t.Fatal("expected command append failure")
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

func TestCancelTaskHandlerAppendsCancelCommandForAssignedTask(t *testing.T) {
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

	seedAssignableAgent(t, ctx, pool, "agent-cancel-1", []string{})
	assignHandler := commands.NewAssignTaskHandlerWithTx(NewAssignTaskTxRunner(pool), pickFirstAgentSelector{})
	assigned, err := assignHandler.Handle(ctx, commands.AssignTaskCommand{
		LeaderEpoch: lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task through handler: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
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
from agent_command
where task_id = $1
  and command_type = 'cancel'
order by created_at desc
limit 1
`, taskID).Scan(&payloadBytes); err != nil {
		t.Fatalf("load cancel command: %v", err)
	}

	var payload commands.StopTaskCommandPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		t.Fatalf("unmarshal stop payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("expected task id %s, got %s", taskID, payload.TaskID)
	}
	if payload.ExecutionID != assigned.ExecutionID {
		t.Fatalf("expected execution id %q, got %q", assigned.ExecutionID, payload.ExecutionID)
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

func TestCancelTaskHandlerLeavesAssignedTaskUnchangedWhenCancelCommandAppendFails(t *testing.T) {
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

	seedAssignableAgent(t, ctx, pool, "agent-cancel-rollback-1", []string{})
	assignHandler := commands.NewAssignTaskHandlerWithTx(NewAssignTaskTxRunner(pool), pickFirstAgentSelector{})
	assigned, err := assignHandler.Handle(ctx, commands.AssignTaskCommand{
		LeaderEpoch: lease.Epoch,
	})
	if err != nil {
		t.Fatalf("assign task through handler: %v", err)
	}
	if assigned == nil {
		t.Fatal("expected assigned task")
	}

	handler := commands.NewCancelTaskHandlerWithTx(newFailingCancelTaskTxRunner(pool))
	canceled, err := handler.Handle(ctx, commands.CancelTaskCommand{TaskID: taskID})
	if err == nil {
		t.Fatal("expected cancel command append failure")
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
	if currentExecutionID != assigned.ExecutionID {
		t.Fatalf("expected execution id %q to be preserved, got %q", assigned.ExecutionID, currentExecutionID)
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

func TestAgentRepoRegisterHeartbeatAndList(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	pool, cleanup := openRuntimeTestPool(t, ctx)
	defer cleanup()

	agentRepo := NewAgentRepo(pool)
	registerAt := time.UnixMilli(111)
	agent, err := agentRepo.Upsert(ctx, UpsertAgentParams{
		ID:             "agent-a",
		Version:        "1.2.3",
		Capabilities:   []string{"gpu", "cuda"},
		TransportMode:  "pull",
		MaxConcurrency: 2,
		RunningTaskIDs: []string{"task-1"},
		LastSeenAt:     registerAt,
	})
	if err != nil {
		t.Fatalf("upsert agent: %v", err)
	}
	if agent.ID != "agent-a" || agent.Version != "1.2.3" {
		t.Fatalf("unexpected registered agent: %+v", agent)
	}
	if agent.TransportMode != "pull" {
		t.Fatalf("unexpected transport mode: %+v", agent)
	}
	if agent.MaxConcurrency != 2 {
		t.Fatalf("unexpected max concurrency: %+v", agent)
	}
	if !slices.Equal(agent.RunningTaskIDs, []string{"task-1"}) {
		t.Fatalf("unexpected running task ids: %+v", agent.RunningTaskIDs)
	}

	heartbeatAt := registerAt.Add(time.Minute)
	if err := agentRepo.Heartbeat(ctx, HeartbeatAgentParams{
		ID:             "agent-a",
		MaxConcurrency: 3,
		RunningTaskIDs: []string{"task-1", "task-2"},
		LastSeenAt:     heartbeatAt,
	}); err != nil {
		t.Fatalf("heartbeat agent: %v", err)
	}

	agents, err := agentRepo.List(ctx)
	if err != nil {
		t.Fatalf("list agents: %v", err)
	}
	if len(agents) != 1 {
		t.Fatalf("unexpected agent count: %d", len(agents))
	}
	if !agents[0].LastSeenAt.Equal(heartbeatAt) {
		t.Fatalf("unexpected heartbeat timestamp: %s", agents[0].LastSeenAt)
	}
	if agents[0].MaxConcurrency != 3 {
		t.Fatalf("unexpected persisted max concurrency: %+v", agents[0])
	}
	if !slices.Equal(agents[0].Capabilities, []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected persisted capabilities: %+v", agents[0].Capabilities)
	}
	if !slices.Equal(agents[0].RunningTaskIDs, []string{"task-1", "task-2"}) {
		t.Fatalf("unexpected persisted running task ids: %+v", agents[0].RunningTaskIDs)
	}
}

func TestTaskAssignmentRepoCreateAssignment(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	pool, cleanup := openRuntimeTestPool(t, ctx)
	defer cleanup()

	taskRepo := NewTaskRepo(pool)
	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create runtime task: %v", err)
	}

	agentRepo := NewAgentRepo(pool)
	if _, err := agentRepo.Upsert(ctx, UpsertAgentParams{
		ID:             "agent-a",
		Version:        "1.2.3",
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     time.UnixMilli(123),
	}); err != nil {
		t.Fatalf("upsert agent: %v", err)
	}

	assignmentRepo := NewTaskAssignmentRepo(pool)
	assignment, err := assignmentRepo.Create(ctx, CreateTaskAssignmentParams{
		TaskID:      taskID,
		Attempt:     1,
		AgentID:     "agent-a",
		ExecutionID: "exec-1",
		Status:      "assigned",
	})
	if err != nil {
		t.Fatalf("create assignment: %v", err)
	}
	if assignment.ID == 0 {
		t.Fatalf("expected assignment id, got %+v", assignment)
	}
	if assignment.ExecutionID != "exec-1" || assignment.Status != "assigned" {
		t.Fatalf("unexpected assignment payload: %+v", assignment)
	}

	loaded, err := assignmentRepo.GetByExecutionID(ctx, "exec-1")
	if err != nil {
		t.Fatalf("load assignment by execution id: %v", err)
	}
	if loaded == nil || loaded.TaskID != taskID || loaded.AgentID != "agent-a" {
		t.Fatalf("unexpected loaded assignment: %+v", loaded)
	}

	otherTaskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, CreateTaskParams{
		ID:       otherTaskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create second runtime task: %v", err)
	}
	if _, err := assignmentRepo.Create(ctx, CreateTaskAssignmentParams{
		TaskID:      otherTaskID,
		Attempt:     1,
		AgentID:     "agent-a",
		ExecutionID: "exec-1",
		Status:      "assigned",
	}); err == nil {
		t.Fatal("expected duplicate execution_id to fail")
	}
}

func TestAgentCommandRepoAppendClaimAckAndRetry(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	pool, cleanup := openRuntimeTestPool(t, ctx)
	defer cleanup()

	taskRepo := NewTaskRepo(pool)
	assignmentRepo := NewTaskAssignmentRepo(pool)
	agentRepo := NewAgentRepo(pool)
	commandRepo := NewAgentCommandRepo(pool)

	now := time.Now().UTC()
	if _, err := agentRepo.Upsert(ctx, UpsertAgentParams{
		ID:             "agent-direct",
		Version:        "1.0.0",
		TransportMode:  "direct",
		ControlBaseURL: "http://127.0.0.1:18081",
		MaxConcurrency: 1,
		LastSeenAt:     now,
	}); err != nil {
		t.Fatalf("upsert direct agent: %v", err)
	}
	if _, err := agentRepo.Upsert(ctx, UpsertAgentParams{
		ID:             "agent-pull",
		Version:        "1.0.0",
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     now,
	}); err != nil {
		t.Fatalf("upsert pull agent: %v", err)
	}

	taskAssignID := seedTaskAssignment(t, ctx, taskRepo, assignmentRepo, "agent-direct", "exec-direct-1")
	taskPullID := seedTaskAssignment(t, ctx, taskRepo, assignmentRepo, "agent-pull", "exec-pull-1")
	taskExpiredID := seedTaskAssignment(t, ctx, taskRepo, assignmentRepo, "agent-direct", "exec-expired-1")

	assignCommandID := uuid.New()
	assignCommand, err := commandRepo.AppendAssign(ctx, AppendAssignCommandParams{
		CommandID:     assignCommandID,
		AgentID:       "agent-direct",
		TaskID:        taskAssignID.taskID,
		AssignmentID:  taskAssignID.assignmentID,
		TransportMode: "direct",
		Payload:       []byte(`{"type":"assign"}`),
		AvailableAt:   now,
		ExpireAt:      now.Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("append assign command: %v", err)
	}

	cancelCommandID := uuid.New()
	cancelCommand, err := commandRepo.AppendCancel(ctx, AppendCancelCommandParams{
		CommandID:     cancelCommandID,
		AgentID:       "agent-pull",
		TaskID:        taskPullID.taskID,
		AssignmentID:  taskPullID.assignmentID,
		TransportMode: "pull",
		Payload:       []byte(`{"type":"cancel"}`),
		AvailableAt:   now,
		ExpireAt:      now.Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("append cancel command: %v", err)
	}

	expiredCommandID := uuid.New()
	if _, err := commandRepo.AppendAssign(ctx, AppendAssignCommandParams{
		CommandID:     expiredCommandID,
		AgentID:       "agent-direct",
		TaskID:        taskExpiredID.taskID,
		AssignmentID:  taskExpiredID.assignmentID,
		TransportMode: "direct",
		Payload:       []byte(`{"type":"assign-expired"}`),
		AvailableAt:   now,
		ExpireAt:      now.Add(-time.Second),
	}); err != nil {
		t.Fatalf("append expired command: %v", err)
	}

	pushClaims, err := commandRepo.ClaimForPush(ctx, 10, now.Add(time.Minute))
	if err != nil {
		t.Fatalf("claim push commands: %v", err)
	}
	if len(pushClaims) != 1 {
		t.Fatalf("expected one push command, got %d", len(pushClaims))
	}
	if pushClaims[0].CommandID != assignCommandID {
		t.Fatalf("unexpected push command: %+v", pushClaims[0])
	}
	if pushClaims[0].ClaimToken == nil {
		t.Fatalf("expected push command claim token, got %+v", pushClaims[0])
	}

	if err := commandRepo.Ack(ctx, pushClaims[0].CommandID, *pushClaims[0].ClaimToken, now.Add(5*time.Second)); err != nil {
		t.Fatalf("ack push command: %v", err)
	}
	if err := commandRepo.MarkFinished(ctx, pushClaims[0].CommandID, *pushClaims[0].ClaimToken, now.Add(10*time.Second)); err != nil {
		t.Fatalf("finish push command: %v", err)
	}

	finished, err := commandRepo.GetByCommandID(ctx, assignCommandID)
	if err != nil {
		t.Fatalf("load finished command: %v", err)
	}
	if finished == nil || finished.Status != "finished" || finished.AckedAt == nil || finished.FinishedAt == nil {
		t.Fatalf("unexpected finished command: %+v", finished)
	}

	pullClaims, err := commandRepo.ClaimForPull(ctx, "agent-pull", 10, now.Add(time.Minute))
	if err != nil {
		t.Fatalf("claim pull commands: %v", err)
	}
	if len(pullClaims) != 1 {
		t.Fatalf("expected one pull command, got %d", len(pullClaims))
	}
	if pullClaims[0].CommandID != cancelCommandID {
		t.Fatalf("unexpected pull command: %+v", pullClaims[0])
	}
	if pullClaims[0].ClaimToken == nil {
		t.Fatalf("expected pull command claim token, got %+v", pullClaims[0])
	}

	if err := commandRepo.MarkRetry(ctx, pullClaims[0].CommandID, *pullClaims[0].ClaimToken, now.Add(time.Hour), "temporary pull failure"); err != nil {
		t.Fatalf("retry pull command: %v", err)
	}
	retried, err := commandRepo.GetByCommandID(ctx, cancelCommandID)
	if err != nil {
		t.Fatalf("load retried command: %v", err)
	}
	if retried == nil || retried.Status != "pending" {
		t.Fatalf("unexpected retried command: %+v", retried)
	}
	if retried.LastError == nil || *retried.LastError != "temporary pull failure" {
		t.Fatalf("unexpected retried last error: %+v", retried)
	}
	if retried.AttemptCount != 1 {
		t.Fatalf("expected attempt_count to remain 1 after retry, got %+v", retried)
	}

	expiredCount, err := commandRepo.ExpireDue(ctx, now)
	if err != nil {
		t.Fatalf("expire commands: %v", err)
	}
	if expiredCount != 1 {
		t.Fatalf("expected one expired command, got %d", expiredCount)
	}

	expired, err := commandRepo.GetByCommandID(ctx, expiredCommandID)
	if err != nil {
		t.Fatalf("load expired command: %v", err)
	}
	if expired == nil || expired.Status != "expired" {
		t.Fatalf("unexpected expired command: %+v", expired)
	}

	if assignCommand == nil || cancelCommand == nil {
		t.Fatal("expected appended commands")
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
		q := sqlcdb.New(tx)
		return fn(failingAssignTaskTxStore{
			tasks:       newTaskRepo(q),
			agents:      newAgentRepo(q),
			assignments: newTaskAssignmentRepo(q),
		})
	})
}

type failingAssignTaskTxStore struct {
	tasks       *TaskRepo
	agents      *AgentRepo
	assignments *TaskAssignmentRepo
}

func (s failingAssignTaskTxStore) ClaimPendingTask(ctx context.Context) (*commands.PendingTask, error) {
	return s.tasks.ClaimPendingTask(ctx)
}

func (s failingAssignTaskTxStore) ListAssignableAgents(ctx context.Context) ([]commands.AgentRecord, error) {
	agents, err := s.agents.List(ctx)
	if err != nil {
		return nil, err
	}

	items := make([]commands.AgentRecord, 0, len(agents))
	for _, agent := range agents {
		items = append(items, *commandsAgentFromRepo(&agent))
	}
	return items, nil
}

func (s failingAssignTaskTxStore) CreateTaskAssignment(ctx context.Context, params commands.CreateTaskAssignmentParams) (*commands.TaskAssignmentRecord, error) {
	assignment, err := s.assignments.Create(ctx, CreateTaskAssignmentParams{
		TaskID:      params.TaskID,
		Attempt:     params.Attempt,
		AgentID:     params.AgentID,
		ExecutionID: params.ExecutionID,
		Status:      params.Status,
	})
	if err != nil {
		return nil, err
	}

	return &commands.TaskAssignmentRecord{
		ID:          assignment.ID,
		TaskID:      assignment.TaskID,
		Attempt:     assignment.Attempt,
		AgentID:     assignment.AgentID,
		ExecutionID: assignment.ExecutionID,
		Status:      assignment.Status,
	}, nil
}

func (s failingAssignTaskTxStore) AssignClaimedTask(ctx context.Context, params commands.AssignClaimedTaskParams) (*commands.ClaimedTask, error) {
	return s.tasks.AssignClaimedTask(ctx, params)
}

func (failingAssignTaskTxStore) AppendAssignCommand(context.Context, commands.AppendAssignTaskCommandParams) error {
	return errors.New("append command failed")
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
			tasks:       newTaskRepo(sqlcdb.New(tx)),
			assignments: newTaskAssignmentRepo(sqlcdb.New(tx)),
			agents:      newAgentRepo(sqlcdb.New(tx)),
		})
	})
}

type failingCancelTaskTxStore struct {
	tasks       *TaskRepo
	assignments *TaskAssignmentRepo
	agents      *AgentRepo
}

func (s failingCancelTaskTxStore) GetTask(ctx context.Context, taskID uuid.UUID) (*commands.TaskRecord, error) {
	return s.tasks.GetTask(ctx, taskID)
}

func (s failingCancelTaskTxStore) UpdateTask(ctx context.Context, update commands.TaskUpdate) error {
	return s.tasks.UpdateTask(ctx, update)
}

func (s failingCancelTaskTxStore) GetTaskAssignmentByExecutionID(ctx context.Context, executionID string) (*commands.TaskAssignmentRecord, error) {
	assignment, err := s.assignments.GetByExecutionID(ctx, executionID)
	if err != nil || assignment == nil {
		return nil, err
	}
	return &commands.TaskAssignmentRecord{
		ID:          assignment.ID,
		TaskID:      assignment.TaskID,
		Attempt:     assignment.Attempt,
		AgentID:     assignment.AgentID,
		ExecutionID: assignment.ExecutionID,
		Status:      assignment.Status,
	}, nil
}

func (s failingCancelTaskTxStore) GetAgentByID(ctx context.Context, agentID string) (*commands.AgentRecord, error) {
	agent, err := s.agents.GetByID(ctx, agentID)
	if err != nil || agent == nil {
		return nil, err
	}
	return commandsAgentFromRepo(agent), nil
}

func (failingCancelTaskTxStore) AppendCancelCommand(context.Context, commands.AppendCancelTaskCommandParams) error {
	return errors.New("append cancel command failed")
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

func openRuntimeTestPool(t *testing.T, ctx context.Context) (*pgxpool.Pool, func()) {
	t.Helper()

	container, dsn := startRuntimePostgres(t, ctx)

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		_ = testcontainers.TerminateContainer(container)
		t.Fatalf("open sql db: %v", err)
	}

	goose.SetDialect("postgres")
	if err := goose.Up(sqlDB, runtimeMigrationsDir(t)); err != nil {
		_ = sqlDB.Close()
		_ = testcontainers.TerminateContainer(container)
		t.Fatalf("run migrations: %v", err)
	}

	pool, err := appdb.NewPool(ctx, dsn)
	if err != nil {
		_ = sqlDB.Close()
		_ = testcontainers.TerminateContainer(container)
		t.Fatalf("create pool: %v", err)
	}

	cleanup := func() {
		pool.Close()
		_ = sqlDB.Close()
		_ = testcontainers.TerminateContainer(container)
	}
	return pool, cleanup
}

type seededTaskAssignment struct {
	taskID       uuid.UUID
	assignmentID int64
}

func seedTaskAssignment(
	t *testing.T,
	ctx context.Context,
	taskRepo *TaskRepo,
	assignmentRepo *TaskAssignmentRepo,
	agentID string,
	executionID string,
) seededTaskAssignment {
	t.Helper()

	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create runtime task: %v", err)
	}

	assignment, err := assignmentRepo.Create(ctx, CreateTaskAssignmentParams{
		TaskID:      taskID,
		Attempt:     1,
		AgentID:     agentID,
		ExecutionID: executionID,
		Status:      "assigned",
	})
	if err != nil {
		t.Fatalf("create task assignment: %v", err)
	}

	return seededTaskAssignment{
		taskID:       taskID,
		assignmentID: assignment.ID,
	}
}

func seedAssignableAgent(t *testing.T, ctx context.Context, pool *pgxpool.Pool, agentID string, capabilities []string) {
	t.Helper()

	if _, err := NewAgentRepo(pool).Upsert(ctx, UpsertAgentParams{
		ID:             agentID,
		Version:        "test",
		Capabilities:   append([]string(nil), capabilities...),
		TransportMode:  "pull",
		MaxConcurrency: 1,
		LastSeenAt:     time.Now().UTC(),
	}); err != nil {
		t.Fatalf("upsert agent %s: %v", agentID, err)
	}
}

type pickFirstAgentSelector struct{}

func (pickFirstAgentSelector) SelectAgent(_ commands.PendingTask, agents []commands.AgentRecord) *commands.AgentRecord {
	for i := range agents {
		if agents[i].Status == "online" {
			agent := agents[i]
			return &agent
		}
	}
	return nil
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
