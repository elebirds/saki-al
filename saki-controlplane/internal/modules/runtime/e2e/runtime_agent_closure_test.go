package e2e_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimescheduler "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/scheduler"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/internalrpc"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
	"github.com/testcontainers/testcontainers-go"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"
)

func TestRuntimeAgentClosure_AssignRunSucceed(t *testing.T) {
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
	commandRepo := runtimerepo.NewAgentCommandRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(agentRepo),
		commands.NewHeartbeatAgentHandler(agentRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	deliveryServer := internalrpc.NewDeliveryServer(commandRepo)
	ingressMux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	ingressMux.Handle(ingressPath, ingressHandler)
	deliveryPath, deliveryHandler := runtimev1connect.NewAgentDeliveryHandler(deliveryServer)
	ingressMux.Handle(deliveryPath, deliveryHandler)
	ingressHTTPServer := httptest.NewServer(ingressMux)
	defer ingressHTTPServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, ingressHTTPServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID:       "agent-real-e2e-1",
		version:       "test-success",
		transportMode: "direct",
	})
	defer agent.stop(t)

	waitForPoll(t, 20*time.Second, func() bool {
		agents, err := agentRepo.List(ctx)
		if err != nil {
			return false
		}
		for _, agent := range agents {
			if agent.ID == "agent-real-e2e-1" && agent.Version == "test-success" {
				return true
			}
		}
		return false
	}, "expected agent register to reach runtime")

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
			commands.NewAssignTaskHandlerWithTx(
				runtimerepo.NewAssignTaskTxRunner(pool),
				runtimescheduler.NewAgentSelector(),
			),
		),
		"runtime-scheduler",
		"runtime-agent-closure-1",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	dispatchWorker := newDirectDeliveryWorkerForTest(agentRepo, commandRepo)
	waitForPollWithStep(t, 20*time.Second, func() error {
		return dispatchWorker.RunOnce(ctx)
	}, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "succeeded"
	}, fmt.Sprintf("expected task %s to become succeeded\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))
}

func TestRuntimeAgentClosure_CancelRequestsReachAgentAndTaskBecomesCanceled(t *testing.T) {
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
	commandRepo := runtimerepo.NewAgentCommandRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(agentRepo),
		commands.NewHeartbeatAgentHandler(agentRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	deliveryServer := internalrpc.NewDeliveryServer(commandRepo)
	ingressMux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	ingressMux.Handle(ingressPath, ingressHandler)
	deliveryPath, deliveryHandler := runtimev1connect.NewAgentDeliveryHandler(deliveryServer)
	ingressMux.Handle(deliveryPath, deliveryHandler)
	ingressHTTPServer := httptest.NewServer(ingressMux)
	defer ingressHTTPServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, ingressHTTPServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID:       "agent-real-e2e-2",
		version:       "test-cancel",
		transportMode: "direct",
		workerMode:    "block",
	})
	defer agent.stop(t)

	waitForPoll(t, 20*time.Second, func() bool {
		agents, err := agentRepo.List(ctx)
		if err != nil {
			return false
		}
		for _, agent := range agents {
			if agent.ID == "agent-real-e2e-2" && agent.Version == "test-cancel" {
				return true
			}
		}
		return false
	}, "expected blocking agent register to reach runtime")

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
			commands.NewAssignTaskHandlerWithTx(
				runtimerepo.NewAssignTaskTxRunner(pool),
				runtimescheduler.NewAgentSelector(),
			),
		),
		"runtime-scheduler",
		"runtime-agent-closure-2",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	outboxWorker := newDirectDeliveryWorkerForTest(agentRepo, commandRepo)
	waitForPollWithStep(t, 20*time.Second, func() error {
		return outboxWorker.RunOnce(ctx)
	}, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "running"
	}, fmt.Sprintf("expected task %s to become running\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))

	cancelled, err := commands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)).Handle(ctx, commands.CancelTaskCommand{
		TaskID: taskID,
	})
	if err != nil {
		t.Fatalf("cancel task: %v", err)
	}
	if cancelled == nil || cancelled.Status != "cancel_requested" {
		t.Fatalf("expected cancel_requested task after cancel command, got %+v", cancelled)
	}
	// cancel 的新主路径必须先把命令落进 agent_command；否则 delivery worker 不会有东西可投递。
	var cancelCommandStatus string
	if err := pool.QueryRow(ctx, `
select status
from agent_command
where task_id = $1
  and command_type = 'cancel'
order by created_at desc
limit 1
`, taskID).Scan(&cancelCommandStatus); err != nil {
		t.Fatalf("load cancel command before delivery: %v", err)
	}
	if cancelCommandStatus != "pending" {
		t.Fatalf("expected pending cancel command before delivery, got %s", cancelCommandStatus)
	}

	// direct delivery 是轮询模型：单次 tick 可能因为 DB/app 时钟微小偏差暂时拿不到刚写入的命令，
	// e2e 要按真实 loop 反复驱动 worker，直到命令生命周期被推进到 acked/finished。
	waitForPollWithStep(t, 20*time.Second, func() error {
		return outboxWorker.RunOnce(ctx)
	}, func() bool {
		var cancelAcked bool
		var cancelFinished bool
		if err := pool.QueryRow(ctx, `
select acked_at is not null, finished_at is not null
from agent_command
where task_id = $1
  and command_type = 'cancel'
order by created_at desc
limit 1
`, taskID).Scan(&cancelAcked, &cancelFinished); err != nil {
			return false
		}
		return cancelAcked && cancelFinished
	}, fmt.Sprintf("expected cancel command to be acked and finished\ntask=%s\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))

	waitForPoll(t, 20*time.Second, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "canceled"
	}, fmt.Sprintf("expected task %s to become canceled\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))
}

func TestRuntimeAgentClosure_PullAssignRunSucceed(t *testing.T) {
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
	commandRepo := runtimerepo.NewAgentCommandRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(agentRepo),
		commands.NewHeartbeatAgentHandler(agentRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	deliveryServer := internalrpc.NewDeliveryServer(commandRepo)
	mux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	mux.Handle(ingressPath, ingressHandler)
	deliveryPath, deliveryHandler := runtimev1connect.NewAgentDeliveryHandler(deliveryServer)
	mux.Handle(deliveryPath, deliveryHandler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, httpServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID:       "agent-pull-e2e-1",
		version:       "test-pull-success",
		transportMode: "pull",
	})
	defer agent.stop(t)

	waitForPoll(t, 20*time.Second, func() bool {
		agent, err := agentRepo.GetByID(ctx, "agent-pull-e2e-1")
		return err == nil && agent != nil && agent.TransportMode == "pull"
	}, "expected pull agent register to reach runtime")

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
			commands.NewAssignTaskHandlerWithTx(
				runtimerepo.NewAssignTaskTxRunner(pool),
				runtimescheduler.NewAgentSelector(),
			),
		),
		"runtime-scheduler",
		"runtime-agent-pull-1",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	waitForPoll(t, 20*time.Second, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "succeeded"
	}, fmt.Sprintf("expected pull task %s to become succeeded\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))
}

func TestRuntimeAgentClosure_PullCancelRequestsReachAgentAndTaskBecomesCanceled(t *testing.T) {
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
	commandRepo := runtimerepo.NewAgentCommandRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(agentRepo),
		commands.NewHeartbeatAgentHandler(agentRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	deliveryServer := internalrpc.NewDeliveryServer(commandRepo)
	mux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	mux.Handle(ingressPath, ingressHandler)
	deliveryPath, deliveryHandler := runtimev1connect.NewAgentDeliveryHandler(deliveryServer)
	mux.Handle(deliveryPath, deliveryHandler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, httpServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID:       "agent-pull-e2e-2",
		version:       "test-pull-cancel",
		transportMode: "pull",
		workerMode:    "block",
	})
	defer agent.stop(t)

	waitForPoll(t, 20*time.Second, func() bool {
		agent, err := agentRepo.GetByID(ctx, "agent-pull-e2e-2")
		return err == nil && agent != nil && agent.TransportMode == "pull"
	}, "expected blocking pull agent register to reach runtime")

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
			commands.NewAssignTaskHandlerWithTx(
				runtimerepo.NewAssignTaskTxRunner(pool),
				runtimescheduler.NewAgentSelector(),
			),
		),
		"runtime-scheduler",
		"runtime-agent-pull-2",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	waitForPoll(t, 20*time.Second, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "running"
	}, fmt.Sprintf("expected pull task %s to become running\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))

	cancelled, err := commands.NewCancelTaskHandlerWithTx(runtimerepo.NewCancelTaskTxRunner(pool)).Handle(ctx, commands.CancelTaskCommand{
		TaskID: taskID,
	})
	if err != nil {
		t.Fatalf("cancel task: %v", err)
	}
	if cancelled == nil || cancelled.Status != "cancel_requested" {
		t.Fatalf("expected cancel_requested task after cancel command, got %+v", cancelled)
	}

	waitForPoll(t, 20*time.Second, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "canceled"
	}, fmt.Sprintf("expected pull task %s to become canceled\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))
}

func TestRuntimeAgentClosure_RelayAssignRunSucceed(t *testing.T) {
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
	commandRepo := runtimerepo.NewAgentCommandRepo(pool)
	sessionRepo := runtimerepo.NewAgentSessionRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(agentRepo),
		commands.NewHeartbeatAgentHandler(agentRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)

	mux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	mux.Handle(ingressPath, ingressHandler)
	deliveryServer := internalrpc.NewDeliveryServer(commandRepo)
	deliveryPath, deliveryHandler := runtimev1connect.NewAgentDeliveryHandler(deliveryServer)
	mux.Handle(deliveryPath, deliveryHandler)
	relayServer := internalrpc.NewRelayServer("", sessionRepo)
	relayPath, relayHandler := runtimev1connect.NewAgentRelayHandler(relayServer)
	mux.Handle(relayPath, relayHandler)
	httpServer := httptest.NewServer(h2c.NewHandler(mux, &http2.Server{}))
	defer httpServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, httpServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID:       "agent-relay-e2e-1",
		version:       "test-relay-success",
		transportMode: "relay",
	})
	defer agent.stop(t)

	waitForPoll(t, 20*time.Second, func() bool {
		agent, err := agentRepo.GetByID(ctx, "agent-relay-e2e-1")
		return err == nil && agent != nil && agent.TransportMode == "relay"
	}, "expected relay agent register to reach runtime")

	waitForPoll(t, 20*time.Second, func() bool {
		session, err := sessionRepo.GetByAgentID(ctx, "agent-relay-e2e-1")
		return err == nil && session != nil && session.SessionID != ""
	}, "expected relay session to be registered")

	taskID := uuid.New()
	if err := taskRepo.CreateTask(ctx, runtimerepo.CreateTaskParams{
		ID:       taskID,
		TaskType: "predict",
	}); err != nil {
		t.Fatalf("create pending relay task: %v", err)
	}

	leader := runtimescheduler.NewLeaderTicker(
		runtimerepo.NewLeaseRepo(pool),
		runtimescheduler.NewDispatchScan(
			commands.NewAssignTaskHandlerWithTx(
				runtimerepo.NewAssignTaskTxRunner(pool),
				runtimescheduler.NewAgentSelector(),
			),
		),
		"runtime-scheduler",
		"runtime-agent-relay-1",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick relay: %v", err)
	}

	relayWorker := newRelayDeliveryWorkerForTest(httpServer.URL, sessionRepo, commandRepo)
	waitForPollWithStep(t, 20*time.Second, func() error {
		return relayWorker.RunOnce(ctx)
	}, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "succeeded"
	}, fmt.Sprintf("expected relay task %s to become succeeded\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))
}

type runtimeAgentProcessConfig struct {
	agentID       string
	version       string
	transportMode string
	workerMode    string
}

type runtimeAgentProcess struct {
	cancel         context.CancelFunc
	cmd            *exec.Cmd
	done           chan error
	controlBaseURL string
	stdout         bytes.Buffer
	stderr         bytes.Buffer
	waited         bool
	waitErr        error
}

func startRuntimeAgent(
	t *testing.T,
	runtimeBaseURL string,
	agentBinary string,
	workerBinary string,
	cfg runtimeAgentProcessConfig,
) *runtimeAgentProcess {
	t.Helper()

	controlBind, controlBaseURL := reserveLoopbackAddress(t)
	workerCommandJSON := marshalWorkerCommandJSON(t, workerBinary, cfg.workerMode)

	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, agentBinary)
	cmd.Dir = agentModuleDir(t)
	transportMode := cfg.transportMode
	if transportMode == "" {
		transportMode = "direct"
	}
	cmd.Env = append(os.Environ(),
		"RUNTIME_BASE_URL="+runtimeBaseURL,
		"AGENT_CONTROL_BIND="+controlBind,
		"AGENT_CONTROL_BASE_URL=",
		"AGENT_ID="+cfg.agentID,
		"AGENT_VERSION="+cfg.version,
		"AGENT_TRANSPORT_MODE="+transportMode,
		"AGENT_MAX_CONCURRENCY=1",
		"AGENT_HEARTBEAT_INTERVAL=50ms",
		"AGENT_WORKER_COMMAND_JSON="+workerCommandJSON,
	)
	if transportMode == "direct" {
		cmd.Env = append(cmd.Env, "AGENT_CONTROL_BASE_URL="+controlBaseURL)
	}

	agent := &runtimeAgentProcess{
		cancel:         cancel,
		cmd:            cmd,
		done:           make(chan error, 1),
		controlBaseURL: controlBaseURL,
	}
	cmd.Stdout = &agent.stdout
	cmd.Stderr = &agent.stderr

	if err := cmd.Start(); err != nil {
		cancel()
		t.Fatalf("start agent process: %v", err)
	}

	go func() {
		agent.done <- cmd.Wait()
	}()

	waitForAgentHTTPReady(t, agent, 10*time.Second, controlBaseURL+"/healthz")
	return agent
}

func (p *runtimeAgentProcess) stop(t *testing.T) {
	t.Helper()

	if exited, err := p.pollExit(); exited {
		if err == nil {
			return
		}
		t.Fatalf("agent process exited unexpectedly\nstdout:\n%s\nstderr:\n%s\nerr: %v", p.stdout.String(), p.stderr.String(), err)
	}

	p.cancel()

	select {
	case err := <-p.done:
		p.waited = true
		p.waitErr = err
		if err == nil {
			return
		}
		if strings.Contains(err.Error(), "signal: killed") || strings.Contains(err.Error(), "context canceled") {
			return
		}
		t.Fatalf("wait agent process: %v\nstdout:\n%s\nstderr:\n%s", err, p.stdout.String(), p.stderr.String())
	case <-time.After(5 * time.Second):
		_ = p.cmd.Process.Kill()
		t.Fatalf("agent process did not stop in time\nstdout:\n%s\nstderr:\n%s", p.stdout.String(), p.stderr.String())
	}
}

func (p *runtimeAgentProcess) pollExit() (bool, error) {
	if p.waited {
		return true, p.waitErr
	}

	select {
	case err := <-p.done:
		p.waited = true
		p.waitErr = err
		return true, err
	default:
		return false, nil
	}
}

func buildAgentBinary(t *testing.T) string {
	t.Helper()

	binaryPath := filepath.Join(t.TempDir(), "saki-agent")
	cmd := exec.Command("go", "build", "-o", binaryPath, "./cmd/agent")
	cmd.Dir = agentModuleDir(t)
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("build agent binary: %v\n%s", err, string(output))
	}
	return binaryPath
}

func buildLauncherHelperBinary(t *testing.T) string {
	t.Helper()

	binaryPath := filepath.Join(t.TempDir(), "launcher-helper.test")
	cmd := exec.Command("go", "test", "-c", "./internal/plugins/launcher", "-o", binaryPath)
	cmd.Dir = agentModuleDir(t)
	output, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("build launcher helper binary: %v\n%s", err, string(output))
	}
	return binaryPath
}

func marshalWorkerCommandJSON(t *testing.T, workerBinary string, mode string) string {
	t.Helper()

	command := []string{
		"env",
		"SAKI_AGENT_HELPER_PROCESS=1",
	}
	if mode != "" {
		command = append(command, "SAKI_AGENT_HELPER_MODE="+mode)
	}
	command = append(command,
		workerBinary,
		"-test.run=TestLauncherExecutesEphemeralWorkerAndForwardsEvents",
		"--",
	)

	raw, err := json.Marshal(command)
	if err != nil {
		t.Fatalf("marshal worker command: %v", err)
	}
	return string(raw)
}

func reserveLoopbackAddress(t *testing.T) (string, string) {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve loopback address: %v", err)
	}
	defer ln.Close()

	addr := ln.Addr().String()
	return addr, "http://" + addr
}

func waitForAgentHTTPReady(t *testing.T, agent *runtimeAgentProcess, timeout time.Duration, url string) {
	t.Helper()

	waitForPoll(t, timeout, func() bool {
		if exited, err := agent.pollExit(); exited {
			t.Fatalf("agent exited before healthz became ready\nstdout:\n%s\nstderr:\n%s\nerr: %v", agent.stdout.String(), agent.stderr.String(), err)
		}
		resp, err := http.Get(url)
		if err != nil {
			return false
		}
		defer resp.Body.Close()
		return resp.StatusCode == http.StatusOK
	}, "expected http endpoint to become ready: "+url+"\nstdout:\n"+agent.stdout.String()+"\nstderr:\n"+agent.stderr.String())
}

func waitForPoll(t *testing.T, timeout time.Duration, predicate func() bool, message string) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if predicate() {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal(message)
}

func waitForPollWithStep(t *testing.T, timeout time.Duration, step func() error, predicate func() bool, message string) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	var lastErr error
	for time.Now().Before(deadline) {
		lastErr = nil
		if step != nil {
			lastErr = step()
		}
		if lastErr == nil && predicate() {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	if lastErr != nil {
		t.Fatalf("%s\nlast step error: %v", message, lastErr)
	}
	t.Fatal(message)
}

func agentModuleDir(t *testing.T) string {
	t.Helper()

	return filepath.Join(repoRootDir(t), "saki-agent")
}

func repoRootDir(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve caller")
	}
	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..", "..")
}
