package runtime

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

func TestRuntimeRunnerStartsRPCHandlersSchedulerAndOutboxWorker(t *testing.T) {
	ingressCalled := false
	artifactCalled := false

	runner := newRunnerFromAssembly(assembly{
		bind: ":8081",
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
	if runner.server == nil {
		t.Fatal("expected runtime runner to build http server")
	}
	if runner.schedulerLoop == nil {
		t.Fatal("expected scheduler loop to be wired")
	}
	if runner.outboxLoop == nil {
		t.Fatal("expected outbox worker loop to be wired")
	}

	ingressReq := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.AgentIngress/Register", nil)
	ingressResp := httptest.NewRecorder()
	runner.server.Handler.ServeHTTP(ingressResp, ingressReq)
	if !ingressCalled {
		t.Fatal("expected ingress handler to be mounted")
	}
	if ingressResp.Code != http.StatusAccepted {
		t.Fatalf("unexpected ingress status: %d", ingressResp.Code)
	}

	artifactReq := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.ArtifactService/CreateUploadTicket", nil)
	artifactResp := httptest.NewRecorder()
	runner.server.Handler.ServeHTTP(artifactResp, artifactReq)
	if !artifactCalled {
		t.Fatal("expected artifact handler to be mounted")
	}
	if artifactResp.Code != http.StatusCreated {
		t.Fatalf("unexpected artifact status: %d", artifactResp.Code)
	}
}

func TestPlaceholderAgentControlClientMarksAssignEffectForRetry(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeRuntimeOutboxStore{
		claimed: []runtimerepo.OutboxEntry{
			{
				ID:             1,
				Topic:          commands.AssignTaskOutboxTopic,
				AggregateID:    "task-1",
				IdempotencyKey: "runtime.task.assign.v1:exec-1",
				Payload:        []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","agent_id":"agent-1","task_kind":"PREDICTION","task_type":"predict","attempt":1,"max_attempts":3,"resolved_params":{"prompt":"hello"},"depends_on_task_ids":[],"leader_epoch":7}`),
				AvailableAt:    now,
			},
		},
	}
	worker := runtimeeffects.NewWorker(
		store,
		runtimeeffects.NewDispatchEffect(&placeholderAgentControlClient{
			logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
		}),
	)

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}
	if store.markPublished != nil {
		t.Fatalf("expected placeholder transport to avoid mark published, got %+v", store.markPublished)
	}
	if store.markRetry == nil {
		t.Fatal("expected placeholder transport to force retry")
	}
	if store.markRetry.lastError != errPlaceholderAgentControlTransport.Error() {
		t.Fatalf("unexpected retry error: %+v", store.markRetry)
	}
}

func TestWithDefaultOptionsLeavesSchedulerTargetAgentUnset(t *testing.T) {
	opts := withDefaultOptions(Options{})
	if opts.SchedulerTargetAgent != "" {
		t.Fatalf("expected empty scheduler target agent by default, got %q", opts.SchedulerTargetAgent)
	}
}

func TestRuntimeRunnerUsesConfiguredAgentControlBaseURL(t *testing.T) {
	transport := newAgentControlTransport(http.DefaultClient, "http://127.0.0.1:18081", slog.New(slog.NewTextHandler(io.Discard, nil)))
	if _, ok := transport.(*placeholderAgentControlClient); ok {
		t.Fatal("expected configured base url to disable placeholder transport")
	}
}

func TestNewSchedulerTickerSkipsLeaderElectionWhenTargetAgentIsUnset(t *testing.T) {
	leases := &fakeRuntimeLeaseManager{}
	assigner := &fakeRuntimeDispatchTaskAssigner{}

	ticker := newSchedulerTicker(
		withDefaultOptions(Options{}),
		leases,
		assigner,
		slog.New(slog.NewTextHandler(io.Discard, nil)),
	)
	if err := ticker.Tick(context.Background()); err != nil {
		t.Fatalf("tick: %v", err)
	}
	if leases.calls != 0 {
		t.Fatalf("expected scheduler without target agent to skip lease acquisition, got %d calls", leases.calls)
	}
	if assigner.calls != 0 {
		t.Fatalf("expected scheduler without target agent to skip dispatch, got %d calls", assigner.calls)
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

type fakeRuntimeOutboxStore struct {
	claimed       []runtimerepo.OutboxEntry
	markPublished *runtimeMarkPublishedCall
	markRetry     *runtimeMarkRetryCall
}

func (f *fakeRuntimeOutboxStore) ClaimDue(_ context.Context, _ int32, _ time.Time) ([]runtimerepo.OutboxEntry, error) {
	return append([]runtimerepo.OutboxEntry(nil), f.claimed...), nil
}

func (f *fakeRuntimeOutboxStore) MarkPublished(_ context.Context, id int64, claimAvailableAt time.Time) error {
	f.markPublished = &runtimeMarkPublishedCall{id: id, claimAvailableAt: claimAvailableAt}
	return nil
}

func (f *fakeRuntimeOutboxStore) MarkRetry(_ context.Context, id int64, claimAvailableAt, nextAvailableAt time.Time, lastError string) error {
	f.markRetry = &runtimeMarkRetryCall{
		id:               id,
		claimAvailableAt: claimAvailableAt,
		nextAvailableAt:  nextAvailableAt,
		lastError:        lastError,
	}
	return nil
}

type runtimeMarkPublishedCall struct {
	id               int64
	claimAvailableAt time.Time
}

type runtimeMarkRetryCall struct {
	id               int64
	claimAvailableAt time.Time
	nextAvailableAt  time.Time
	lastError        string
}

type fakeRuntimeLeaseManager struct {
	calls int
}

func (f *fakeRuntimeLeaseManager) AcquireOrRenew(context.Context, runtimerepo.AcquireLeaseParams) (*runtimerepo.RuntimeLease, error) {
	f.calls++
	return &runtimerepo.RuntimeLease{}, nil
}

type fakeRuntimeDispatchTaskAssigner struct {
	calls int
}

func (f *fakeRuntimeDispatchTaskAssigner) Handle(context.Context, commands.AssignTaskCommand) (*commands.TaskRecord, error) {
	f.calls++
	return nil, nil
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
