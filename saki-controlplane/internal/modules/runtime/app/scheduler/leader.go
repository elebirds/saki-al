package scheduler

import (
	"context"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

type LeaseManager interface {
	AcquireOrRenew(ctx context.Context, params repo.AcquireLeaseParams) (*repo.RuntimeLease, error)
}

type LeaderTicker struct {
	leases    LeaseManager
	assigner  Assigner
	leaseName string
	holder    string
	ttl       time.Duration
	now       func() time.Time
}

func NewLeaderTicker(
	leases LeaseManager,
	assigner Assigner,
	leaseName string,
	holder string,
	ttl time.Duration,
) *LeaderTicker {
	return &LeaderTicker{
		leases:    leases,
		assigner:  assigner,
		leaseName: leaseName,
		holder:    holder,
		ttl:       ttl,
		now:       time.Now,
	}
}
