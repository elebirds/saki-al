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

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimescheduler "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/scheduler"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/internalrpc"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
	"github.com/testcontainers/testcontainers-go"
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
	executorRepo := runtimerepo.NewExecutorRepo(pool)
	outboxRepo := runtimerepo.NewOutboxRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(executorRepo),
		commands.NewHeartbeatAgentHandler(executorRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	ingressMux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	ingressMux.Handle(ingressPath, ingressHandler)
	ingressHTTPServer := httptest.NewServer(ingressMux)
	defer ingressHTTPServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, ingressHTTPServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID: "agent-real-e2e-1",
		version: "test-success",
	})
	defer agent.stop(t)

	waitForPoll(t, 10*time.Second, func() bool {
		executors, err := executorRepo.List(ctx)
		if err != nil {
			return false
		}
		for _, executor := range executors {
			if executor.ID == "agent-real-e2e-1" && executor.Version == "test-success" {
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
			commands.NewAssignTaskHandlerWithTx(runtimerepo.NewAssignTaskTxRunner(pool)),
			"agent-real-e2e-1",
		),
		"runtime-scheduler",
		"runtime-agent-closure-1",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	dispatchWorker := runtimeeffects.NewWorker(
		outboxRepo,
		runtimeeffects.NewDispatchEffect(connectDispatchClient{
			client: runtimev1connect.NewAgentControlClient(http.DefaultClient, agent.controlBaseURL),
		}),
	)
	if err := dispatchWorker.RunOnce(ctx); err != nil {
		t.Fatalf("dispatch worker run once: %v\nagent stderr:\n%s", err, agent.stderr.String())
	}

	waitForPoll(t, 10*time.Second, func() bool {
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
	executorRepo := runtimerepo.NewExecutorRepo(pool)
	outboxRepo := runtimerepo.NewOutboxRepo(pool)
	outboxWriter := runtimerepo.NewCommandOutboxWriter(pool)

	ingressServer := internalrpc.NewRuntimeServer(
		commands.NewRegisterAgentHandler(executorRepo),
		commands.NewHeartbeatAgentHandler(executorRepo),
		commands.NewStartTaskHandler(taskRepo),
		commands.NewCompleteTaskHandler(taskRepo, outboxWriter),
		commands.NewFailTaskHandler(taskRepo),
		commands.NewConfirmTaskCanceledHandler(taskRepo),
	)
	ingressMux := http.NewServeMux()
	ingressPath, ingressHandler := runtimev1connect.NewAgentIngressHandler(ingressServer)
	ingressMux.Handle(ingressPath, ingressHandler)
	ingressHTTPServer := httptest.NewServer(ingressMux)
	defer ingressHTTPServer.Close()

	agentBinary := buildAgentBinary(t)
	workerBinary := buildLauncherHelperBinary(t)
	agent := startRuntimeAgent(t, ingressHTTPServer.URL, agentBinary, workerBinary, runtimeAgentProcessConfig{
		agentID:    "agent-real-e2e-2",
		version:    "test-cancel",
		workerMode: "block",
	})
	defer agent.stop(t)

	waitForPoll(t, 10*time.Second, func() bool {
		executors, err := executorRepo.List(ctx)
		if err != nil {
			return false
		}
		for _, executor := range executors {
			if executor.ID == "agent-real-e2e-2" && executor.Version == "test-cancel" {
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
			commands.NewAssignTaskHandlerWithTx(runtimerepo.NewAssignTaskTxRunner(pool)),
			"agent-real-e2e-2",
		),
		"runtime-scheduler",
		"runtime-agent-closure-2",
		time.Minute,
	)
	if err := leader.Tick(ctx); err != nil {
		t.Fatalf("leader tick: %v", err)
	}

	controlClient := connectAgentControlEffectClient{
		client: runtimev1connect.NewAgentControlClient(http.DefaultClient, agent.controlBaseURL),
	}
	outboxWorker := runtimeeffects.NewWorker(
		outboxRepo,
		runtimeeffects.NewDispatchEffect(controlClient),
		runtimeeffects.NewStopEffect(controlClient),
	)
	if err := outboxWorker.RunOnce(ctx); err != nil {
		t.Fatalf("dispatch worker run once: %v\nagent stderr:\n%s", err, agent.stderr.String())
	}

	waitForPoll(t, 10*time.Second, func() bool {
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

	if err := outboxWorker.RunOnce(ctx); err != nil {
		t.Fatalf("stop worker run once: %v\nagent stdout:\n%s\nagent stderr:\n%s", err, agent.stdout.String(), agent.stderr.String())
	}

	waitForPoll(t, 10*time.Second, func() bool {
		task, err := taskRepo.GetTask(ctx, taskID)
		return err == nil && task != nil && task.Status == "canceled"
	}, fmt.Sprintf("expected task %s to become canceled\nagent stdout:\n%s\nagent stderr:\n%s", taskID, agent.stdout.String(), agent.stderr.String()))
}

type runtimeAgentProcessConfig struct {
	agentID    string
	version    string
	workerMode string
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
	cmd.Env = append(os.Environ(),
		"RUNTIME_BASE_URL="+runtimeBaseURL,
		"AGENT_CONTROL_BIND="+controlBind,
		"AGENT_ID="+cfg.agentID,
		"AGENT_VERSION="+cfg.version,
		"AGENT_HEARTBEAT_INTERVAL=50ms",
		"AGENT_WORKER_COMMAND_JSON="+workerCommandJSON,
	)

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

type connectAgentControlEffectClient struct {
	client runtimev1connect.AgentControlClient
}

func (c connectAgentControlEffectClient) AssignTask(ctx context.Context, req *runtimev1.AssignTaskRequest) error {
	_, err := c.client.AssignTask(ctx, connect.NewRequest(req))
	return err
}

func (c connectAgentControlEffectClient) StopTask(ctx context.Context, req *runtimev1.StopTaskRequest) error {
	_, err := c.client.StopTask(ctx, connect.NewRequest(req))
	return err
}
