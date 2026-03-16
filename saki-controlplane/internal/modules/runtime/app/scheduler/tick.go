package scheduler

import (
	"context"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

func (t *LeaderTicker) Tick(ctx context.Context) error {
	lease, err := t.leases.AcquireOrRenew(ctx, repo.AcquireLeaseParams{
		Name:       t.leaseName,
		Holder:     t.holder,
		LeaseUntil: t.now().Add(t.ttl),
	})
	if err != nil {
		return err
	}
	if lease == nil || lease.Holder != t.holder {
		return nil
	}

	return t.assigner.Dispatch(ctx, DispatchCommand{
		LeaderEpoch: lease.Epoch,
	})
}
