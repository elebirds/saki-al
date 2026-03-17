package runtime

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimeeffects "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/effects"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

func TestRuntimeRunnerStartsIngressSchedulerAndOutboxWorker(t *testing.T) {
	called := false

	runner := newRunnerFromAssembly(assembly{
		bind:        ":8081",
		ingressPath: "/saki.runtime.v1.AgentIngress/",
		ingressHandler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			called = true
			w.WriteHeader(http.StatusAccepted)
		}),
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

	req := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.AgentIngress/Register", nil)
	resp := httptest.NewRecorder()
	runner.server.Handler.ServeHTTP(resp, req)

	if !called {
		t.Fatal("expected ingress handler to be mounted")
	}
	if resp.Code != http.StatusAccepted {
		t.Fatalf("unexpected ingress status: %d", resp.Code)
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
