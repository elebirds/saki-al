package recovery

import (
	"context"
	"testing"
	"time"
)

func TestRecovery_RequeuesAssignedTaskWhenAssignNotAcked(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeRecoveryStore{}
	worker := NewWorker(store, Policy{
		AssignAckTimeout:      30 * time.Second,
		AgentHeartbeatTimeout: time.Minute,
	})
	worker.now = func() time.Time { return now }

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run recovery once: %v", err)
	}

	if !store.requeueBefore.Equal(now.Add(-30 * time.Second)) {
		t.Fatalf("unexpected requeue cutoff: %s", store.requeueBefore)
	}
}

func TestRecovery_FailsRunningTaskWhenAgentLost(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeRecoveryStore{}
	worker := NewWorker(store, Policy{
		AssignAckTimeout:      30 * time.Second,
		AgentHeartbeatTimeout: 45 * time.Second,
	})
	worker.now = func() time.Time { return now }

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run recovery once: %v", err)
	}

	want := now.Add(-45 * time.Second)
	if !store.failBefore.Equal(want) {
		t.Fatalf("unexpected offline cutoff: got=%s want=%s", store.failBefore, want)
	}
}

func TestRecovery_ClosesStaleCancelWhenAgentOffline(t *testing.T) {
	now := time.Unix(1700000000, 0)
	store := &fakeRecoveryStore{}
	worker := NewWorker(store, Policy{
		AssignAckTimeout:      30 * time.Second,
		AgentHeartbeatTimeout: 15 * time.Second,
	})
	worker.now = func() time.Time { return now }

	if err := worker.RunOnce(context.Background()); err != nil {
		t.Fatalf("run recovery once: %v", err)
	}

	want := now.Add(-15 * time.Second)
	if !store.cancelBefore.Equal(want) {
		t.Fatalf("unexpected cancel cutoff: got=%s want=%s", store.cancelBefore, want)
	}
	if store.callOrder[0] != "mark_offline" || store.callOrder[1] != "requeue_assign" || store.callOrder[2] != "fail_running" || store.callOrder[3] != "cancel_offline" {
		t.Fatalf("unexpected recovery call order: %+v", store.callOrder)
	}
}

type fakeRecoveryStore struct {
	requeueBefore time.Time
	failBefore    time.Time
	cancelBefore  time.Time
	offlineBefore time.Time
	callOrder     []string
}

func (f *fakeRecoveryStore) MarkOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	_ = ctx
	f.offlineBefore = offlineBefore
	f.callOrder = append(f.callOrder, "mark_offline")
	return 0, nil
}

func (f *fakeRecoveryStore) RequeueAssignedTasksWithoutAck(ctx context.Context, ackBefore time.Time) (int64, error) {
	_ = ctx
	f.requeueBefore = ackBefore
	f.callOrder = append(f.callOrder, "requeue_assign")
	return 0, nil
}

func (f *fakeRecoveryStore) FailRunningTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	_ = ctx
	f.failBefore = offlineBefore
	f.callOrder = append(f.callOrder, "fail_running")
	return 0, nil
}

func (f *fakeRecoveryStore) CancelRequestedTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	_ = ctx
	f.cancelBefore = offlineBefore
	f.callOrder = append(f.callOrder, "cancel_offline")
	return 0, nil
}
