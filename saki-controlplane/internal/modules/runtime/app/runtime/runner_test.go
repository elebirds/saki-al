package runtime

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
)

func TestRuntimeRunnerStartsRPCHandlersSchedulerAndOutboxWorker(t *testing.T) {
	ingressCalled := false
	artifactCalled := false

	runner := newRunnerFromAssembly(assembly{
		bind: ":8081",
		roles: NewRoleSet(
			string(RuntimeRoleIngress),
			string(RuntimeRoleScheduler),
			string(RuntimeRoleDelivery),
		),
		rpcHandlers: []rpcHandlerMount{
			{
				path: "/saki.runtime.v1.AgentIngress/",
				handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					ingressCalled = true
					w.WriteHeader(http.StatusAccepted)
				}),
			},
			{
				path: "/saki.runtime.v1.ArtifactService/",
				handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					artifactCalled = true
					w.WriteHeader(http.StatusCreated)
				}),
			},
		},
		schedulerTicker: fakeSchedulerTicker{},
		outboxWorker:    fakeOutboxWorker{},
	})
	if runner.Server() == nil {
		t.Fatal("expected runtime runner to build http server")
	}
	if len(runner.process.background) != 2 {
		t.Fatalf("expected scheduler and delivery loops to be wired, got %d loops", len(runner.process.background))
	}

	ingressReq := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.AgentIngress/Register", nil)
	ingressResp := httptest.NewRecorder()
	runner.Server().Handler.ServeHTTP(ingressResp, ingressReq)
	if !ingressCalled {
		t.Fatal("expected ingress handler to be mounted")
	}
	if ingressResp.Code != http.StatusAccepted {
		t.Fatalf("unexpected ingress status: %d", ingressResp.Code)
	}

	artifactReq := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.ArtifactService/CreateUploadTicket", nil)
	artifactResp := httptest.NewRecorder()
	runner.Server().Handler.ServeHTTP(artifactResp, artifactReq)
	if !artifactCalled {
		t.Fatal("expected artifact handler to be mounted")
	}
	if artifactResp.Code != http.StatusCreated {
		t.Fatalf("unexpected artifact status: %d", artifactResp.Code)
	}
}

func TestRunnerOnlyStartsEnabledRoles(t *testing.T) {
	runner := newRunnerFromAssembly(assembly{
		bind:  ":8081",
		roles: NewRoleSet(string(RuntimeRoleScheduler)),
		rpcHandlers: []rpcHandlerMount{
			{
				path: "/saki.runtime.v1.AgentIngress/",
				handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					w.WriteHeader(http.StatusAccepted)
				}),
			},
		},
		schedulerTicker: fakeSchedulerTicker{},
		outboxWorker:    fakeOutboxWorker{},
	})

	if runner.Server() == nil {
		t.Fatal("expected runtime runner to build http server")
	}
	if len(runner.process.background) != 1 {
		t.Fatalf("expected only scheduler loop to be wired, got %d loops", len(runner.process.background))
	}

	req := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.AgentIngress/Register", nil)
	resp := httptest.NewRecorder()
	runner.Server().Handler.ServeHTTP(resp, req)
	if resp.Code != http.StatusNotFound {
		t.Fatalf("expected ingress handler to be disabled, got %d", resp.Code)
	}
}

func TestNewDeliveryWorkerMarksRetryWhenDirectAgentHasNoControlURL(t *testing.T) {
	claimToken := uuid.New()
	store := &fakeRuntimeCommandStore{
		claimedCommands: []runtimerepo.AgentCommand{
			{
				CommandID:     uuid.New(),
				AgentID:       "agent-1",
				CommandType:   "assign",
				TransportMode: "direct",
				Payload:       []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","agent_id":"agent-1","task_kind":"PREDICTION","task_type":"predict","attempt":1,"max_attempts":3,"resolved_params":{"prompt":"hello"},"depends_on_task_ids":[],"leader_epoch":7}`),
				ClaimToken:    &claimToken,
			},
		},
	}
	worker := newDeliveryWorker(
		store,
		&fakeRuntimeAgentStore{
			agents: map[string]*runtimerepo.Agent{
				"agent-1": {
					ID:            "agent-1",
					TransportMode: "direct",
				},
			},
		},
		http.DefaultClient,
	)

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}
	if store.finish != nil || store.ack != nil {
		t.Fatalf("expected missing direct endpoint to avoid ack/finish, got ack=%+v finish=%+v", store.ack, store.finish)
	}
	if store.retry == nil {
		t.Fatal("expected placeholder transport to force retry")
	}
	if !strings.Contains(store.retry.lastError, "control_base_url") {
		t.Fatalf("unexpected retry error: %+v", store.retry)
	}
	if store.retry.nextAvailableAt.IsZero() {
		t.Fatalf("expected retry to schedule next attempt, got %+v", store.retry)
	}
}

func TestWithDefaultOptionsSetsRecoveryTimeouts(t *testing.T) {
	opts := withDefaultOptions(Options{})
	if opts.RecoveryAssignAckTimeout != 30*time.Second {
		t.Fatalf("unexpected recovery assign ack timeout: %s", opts.RecoveryAssignAckTimeout)
	}
	if opts.RecoveryAgentHeartbeatTimeout != 30*time.Second {
		t.Fatalf("unexpected recovery heartbeat timeout: %s", opts.RecoveryAgentHeartbeatTimeout)
	}
}

func TestNewSchedulerTickerRunsDynamicDispatchWhenTargetAgentIsUnset(t *testing.T) {
	leases := &fakeRuntimeLeaseManager{}
	assigner := &fakeRuntimeDispatchTaskAssigner{}

	ticker := newSchedulerTicker(
		withDefaultOptions(Options{}),
		leases,
		assigner,
		nil,
	)
	if err := ticker.Tick(context.Background()); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if leases.calls != 1 {
		t.Fatalf("expected scheduler to still acquire lease for dynamic dispatch, got %d calls", leases.calls)
	}
	if assigner.calls != 1 {
		t.Fatalf("expected scheduler to dispatch dynamically without target agent, got %d calls", assigner.calls)
	}
}

func TestProbeArtifactProviderTreatsObjectNotFoundAsReady(t *testing.T) {
	provider := &fakeRuntimeStorageProvider{statErr: storage.ErrObjectNotFound}
	if err := probeArtifactProvider(context.Background(), provider); err != nil {
		t.Fatalf("expected probe to pass on object not found, got %v", err)
	}
	if provider.lastStatKey == "" {
		t.Fatal("expected probe to call StatObject")
	}
}

func TestProbeArtifactProviderFailsOnUnexpectedError(t *testing.T) {
	wantErr := errors.New("minio unavailable")
	provider := &fakeRuntimeStorageProvider{statErr: wantErr}
	err := probeArtifactProvider(context.Background(), provider)
	if !errors.Is(err, wantErr) {
		t.Fatalf("expected probe error %v, got %v", wantErr, err)
	}
}

func TestRuntimeNewFailsWhenArtifactProviderProbeFails(t *testing.T) {
	runner, err := New(context.Background(), Options{
		DatabaseDSN: "://bad-dsn",
		AssetProvider: &fakeRuntimeStorageProvider{
			statErr: errors.New("probe boom"),
		},
	}, nil)
	if err == nil {
		t.Fatal("expected New to fail")
	}
	if runner != nil {
		t.Fatalf("expected nil runner on startup failure, got %#v", runner)
	}
	if !strings.Contains(err.Error(), "probe") {
		t.Fatalf("expected probe failure in error, got %v", err)
	}
}

type fakeSchedulerTicker struct{}

func (fakeSchedulerTicker) Tick(context.Context) error {
	return nil
}

type fakeOutboxWorker struct{}

func (fakeOutboxWorker) RunOnce(context.Context) error {
	return nil
}

type fakeRuntimeCommandStore struct {
	claimedCommands []runtimerepo.AgentCommand
	ack             *runtimeAckCall
	finish          *runtimeFinishCall
	retry           *runtimeRetryCall
}

func (f *fakeRuntimeCommandStore) ClaimForPush(_ context.Context, _ int32, _ time.Time) ([]runtimerepo.AgentCommand, error) {
	return append([]runtimerepo.AgentCommand(nil), f.claimedCommands...), nil
}

func (f *fakeRuntimeCommandStore) Ack(_ context.Context, commandID, claimToken uuid.UUID, at time.Time) error {
	f.ack = &runtimeAckCall{commandID: commandID, claimToken: claimToken, at: at}
	return nil
}

func (f *fakeRuntimeCommandStore) MarkFinished(_ context.Context, commandID, claimToken uuid.UUID, at time.Time) error {
	f.finish = &runtimeFinishCall{commandID: commandID, claimToken: claimToken, at: at}
	return nil
}

func (f *fakeRuntimeCommandStore) MarkRetry(_ context.Context, commandID, claimToken uuid.UUID, nextAvailableAt time.Time, lastError string) error {
	f.retry = &runtimeRetryCall{
		commandID:       commandID,
		claimToken:      claimToken,
		nextAvailableAt: nextAvailableAt,
		lastError:       lastError,
	}
	return nil
}

type runtimeAckCall struct {
	commandID  uuid.UUID
	claimToken uuid.UUID
	at         time.Time
}

type runtimeFinishCall struct {
	commandID  uuid.UUID
	claimToken uuid.UUID
	at         time.Time
}

type runtimeRetryCall struct {
	commandID       uuid.UUID
	claimToken      uuid.UUID
	nextAvailableAt time.Time
	lastError       string
}

type fakeRuntimeLeaseManager struct {
	calls int
}

func (f *fakeRuntimeLeaseManager) AcquireOrRenew(_ context.Context, params runtimerepo.AcquireLeaseParams) (*runtimerepo.RuntimeLease, error) {
	f.calls++
	return &runtimerepo.RuntimeLease{
		Holder: params.Holder,
		Epoch:  1,
	}, nil
}

type fakeRuntimeDispatchTaskAssigner struct {
	calls int
}

func (f *fakeRuntimeDispatchTaskAssigner) Handle(context.Context, commands.AssignTaskCommand) (*commands.AssignResult, error) {
	f.calls++
	return nil, nil
}

type fakeRuntimeAgentStore struct {
	agents map[string]*runtimerepo.Agent
}

func (f *fakeRuntimeAgentStore) GetByID(_ context.Context, agentID string) (*runtimerepo.Agent, error) {
	if f.agents == nil {
		return nil, nil
	}
	return f.agents[agentID], nil
}

type fakeRuntimeStorageProvider struct {
	statErr     error
	lastStatKey string
}

func (f *fakeRuntimeStorageProvider) Bucket() string {
	return "assets"
}

func (f *fakeRuntimeStorageProvider) SignPutObject(context.Context, string, time.Duration, string) (string, error) {
	return "", nil
}

func (f *fakeRuntimeStorageProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", nil
}

func (f *fakeRuntimeStorageProvider) StatObject(_ context.Context, objectKey string) (*storage.ObjectStat, error) {
	f.lastStatKey = objectKey
	return nil, f.statErr
}

func (f *fakeRuntimeStorageProvider) DownloadObject(context.Context, string, string) error {
	return nil
}
