package scheduler

import (
	"context"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

func TestLeaderTickAcquiresLeaseAndDispatchesAssignCommand(t *testing.T) {
	leases := &fakeLeaseManager{
		lease: &repo.RuntimeLease{
			Name:       "runtime-scheduler",
			Holder:     "runtime-1",
			Epoch:      3,
			LeaseUntil: time.Now().Add(time.Minute),
		},
	}
	assigner := &fakeAssigner{}

	ticker := NewLeaderTicker(leases, assigner, "runtime-scheduler", "runtime-1", time.Minute)
	if err := ticker.Tick(context.Background()); err != nil {
		t.Fatalf("tick: %v", err)
	}

	if leases.calls != 1 {
		t.Fatalf("expected one lease call, got %d", leases.calls)
	}
	if assigner.calls != 1 {
		t.Fatalf("expected one assign dispatch, got %d", assigner.calls)
	}
	if assigner.last.LeaderEpoch != 3 {
		t.Fatalf("unexpected leader epoch: %+v", assigner.last)
	}
}

type fakeLeaseManager struct {
	lease *repo.RuntimeLease
	calls int
}

func (f *fakeLeaseManager) AcquireOrRenew(context.Context, repo.AcquireLeaseParams) (*repo.RuntimeLease, error) {
	f.calls++
	return f.lease, nil
}

type fakeAssigner struct {
	calls int
	last  DispatchCommand
}

func (f *fakeAssigner) Dispatch(_ context.Context, command DispatchCommand) error {
	f.calls++
	f.last = command
	return nil
}
