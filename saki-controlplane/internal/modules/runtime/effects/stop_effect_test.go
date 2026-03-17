package effects

import (
	"context"
	"errors"
	"testing"
	"time"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

func TestStopEffectStopTaskTopicInvokesControlClient(t *testing.T) {
	client := &fakeStopClient{}
	effect := NewStopEffect(client)

	err := effect.Apply(context.Background(), commands.OutboxEvent{
		Topic:       "runtime.task.stop.v1",
		AggregateID: "550e8400-e29b-41d4-a716-446655440000",
		Payload:     []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","agent_id":"agent-1","reason":"cancel_requested","leader_epoch":7}`),
	})
	if err != nil {
		t.Fatalf("apply stop effect: %v", err)
	}

	if client.last == nil {
		t.Fatal("expected stop request")
	}
	if client.last.TaskId != "550e8400-e29b-41d4-a716-446655440000" {
		t.Fatalf("unexpected stop request task id: %+v", client.last)
	}
	if client.last.ExecutionId != "exec-1" || client.last.Reason != "cancel_requested" {
		t.Fatalf("unexpected stop request: %+v", client.last)
	}
}

func TestWorkerMarksPublishedWhenEffectsSucceed(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeOutboxStore{
		claimed: []runtimerepo.OutboxEntry{
			{
				ID:             1,
				Topic:          commands.AssignTaskOutboxTopic,
				AggregateID:    "task-1",
				IdempotencyKey: "runtime.task.assign.v1:exec-1",
				Payload:        []byte(`{"task_id":"task-1"}`),
				AvailableAt:    now.Add(30 * time.Second),
			},
		},
	}
	assignEffect := &fakeEffect{topic: commands.AssignTaskOutboxTopic}
	stopEffect := &fakeEffect{topic: commands.StopTaskOutboxTopic}
	worker := NewWorker(store, assignEffect, stopEffect)
	worker.now = func() time.Time { return now }
	worker.claimLimit = 1
	worker.claimTTL = 30 * time.Second
	worker.retryBackoff = time.Minute

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}

	if len(assignEffect.applied) != 1 {
		t.Fatalf("expected assign effect to be applied once, got %d", len(assignEffect.applied))
	}
	if len(stopEffect.applied) != 0 {
		t.Fatalf("expected stop effect to be skipped, got %d", len(stopEffect.applied))
	}
	if store.markPublished == nil {
		t.Fatal("expected mark published")
	}
	if store.markPublished.id != 1 {
		t.Fatalf("unexpected published id: %+v", store.markPublished)
	}
	if !store.markPublished.claimAvailableAt.Equal(now.Add(30 * time.Second)) {
		t.Fatalf("unexpected claim available at: %+v", store.markPublished)
	}
	if store.markRetry != nil {
		t.Fatalf("expected no retry mark, got %+v", store.markRetry)
	}
}

func TestWorkerMarksRetryWhenEffectFails(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeOutboxStore{
		claimed: []runtimerepo.OutboxEntry{
			{
				ID:             7,
				Topic:          "runtime.task.stop.v1",
				AggregateID:    "task-7",
				IdempotencyKey: "runtime.task.stop.v1:exec-7",
				Payload:        []byte(`{"task_id":"task-7"}`),
				AvailableAt:    now.Add(15 * time.Second),
			},
		},
	}
	effect := &fakeEffect{topic: commands.StopTaskOutboxTopic, err: errors.New("client unavailable")}
	worker := NewWorker(store, effect)
	worker.now = func() time.Time { return now }
	worker.claimLimit = 1
	worker.claimTTL = 15 * time.Second
	worker.retryBackoff = 2 * time.Minute

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}

	if store.markPublished != nil {
		t.Fatalf("expected no publish mark, got %+v", store.markPublished)
	}
	if store.markRetry == nil {
		t.Fatal("expected retry mark")
	}
	if store.markRetry.id != 7 {
		t.Fatalf("unexpected retry id: %+v", store.markRetry)
	}
	if !store.markRetry.claimAvailableAt.Equal(now.Add(15 * time.Second)) {
		t.Fatalf("unexpected retry claim available at: %+v", store.markRetry)
	}
	if !store.markRetry.nextAvailableAt.Equal(now.Add(2 * time.Minute)) {
		t.Fatalf("unexpected retry next available at: %+v", store.markRetry)
	}
	if store.markRetry.lastError != "client unavailable" {
		t.Fatalf("unexpected retry error: %+v", store.markRetry)
	}
}

func TestWorkerMarksRetryWhenNoEffectRegisteredForTopic(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeOutboxStore{
		claimed: []runtimerepo.OutboxEntry{
			{
				ID:             11,
				Topic:          "runtime.task.legacy",
				AggregateID:    "task-11",
				IdempotencyKey: "runtime.task.legacy:11",
				Payload:        []byte(`{"task_id":"task-11"}`),
				AvailableAt:    now.Add(10 * time.Second),
			},
		},
	}
	worker := NewWorker(store, &fakeEffect{topic: commands.AssignTaskOutboxTopic})
	worker.now = func() time.Time { return now }
	worker.claimLimit = 1
	worker.claimTTL = 10 * time.Second
	worker.retryBackoff = time.Minute

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run worker once: %v", err)
	}

	if store.markPublished != nil {
		t.Fatalf("expected no publish mark, got %+v", store.markPublished)
	}
	if store.markRetry == nil {
		t.Fatal("expected retry mark for unknown topic")
	}
	if store.markRetry.id != 11 {
		t.Fatalf("unexpected retry id: %+v", store.markRetry)
	}
	if store.markRetry.lastError != "no effect registered for topic runtime.task.legacy" {
		t.Fatalf("unexpected retry error: %+v", store.markRetry)
	}
}

type fakeStopClient struct {
	last *runtimev1.StopTaskRequest
}

func (f *fakeStopClient) StopTask(_ context.Context, req *runtimev1.StopTaskRequest) error {
	f.last = req
	return nil
}

type fakeEffect struct {
	topic   string
	applied []commands.OutboxEvent
	err     error
}

func (f *fakeEffect) Topic() string {
	return f.topic
}

func (f *fakeEffect) Apply(_ context.Context, event commands.OutboxEvent) error {
	f.applied = append(f.applied, event)
	return f.err
}

type fakeOutboxStore struct {
	claimed []runtimerepo.OutboxEntry

	markPublished *markPublishedCall
	markRetry     *markRetryCall
}

func (f *fakeOutboxStore) ClaimDue(_ context.Context, limit int32, claimUntil time.Time) ([]runtimerepo.OutboxEntry, error) {
	if limit != 1 {
		panic("unexpected limit")
	}
	_ = claimUntil
	return append([]runtimerepo.OutboxEntry(nil), f.claimed...), nil
}

func (f *fakeOutboxStore) MarkPublished(_ context.Context, id int64, claimAvailableAt time.Time) error {
	f.markPublished = &markPublishedCall{id: id, claimAvailableAt: claimAvailableAt}
	return nil
}

func (f *fakeOutboxStore) MarkRetry(_ context.Context, id int64, claimAvailableAt, nextAvailableAt time.Time, lastError string) error {
	f.markRetry = &markRetryCall{
		id:               id,
		claimAvailableAt: claimAvailableAt,
		nextAvailableAt:  nextAvailableAt,
		lastError:        lastError,
	}
	return nil
}

type markPublishedCall struct {
	id               int64
	claimAvailableAt time.Time
}

type markRetryCall struct {
	id               int64
	claimAvailableAt time.Time
	nextAvailableAt  time.Time
	lastError        string
}
