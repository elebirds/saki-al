package controlplane

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/rs/zerolog"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-dispatcher/internal/repo"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

type CommandResult struct {
	CommandID string
	Status    string
	Message   string
	RequestID string
}

type ControlplaneQuerier interface {
	db.Querier
	WithTx(tx pgx.Tx) *db.Queries
}

type Service struct {
	pool                    *pgxpool.Pool
	queries                 ControlplaneQuerier
	dispatcher              *dispatch.Dispatcher
	domainClient            *runtime_domain_client.Client
	dispatchLockKey         int64
	simCooldown             time.Duration
	stopForceCancelAfter    time.Duration
	predictionTTLDays       int
	predictionTTLKeepRounds int
	roundAffinityWait       time.Duration
	strictModelHandoff      bool
	lastTTLCleanupAt        time.Time
	ttlCleanupInterval      time.Duration
	logger                  zerolog.Logger
}

func NewService(
	repository *repo.RuntimeRepo,
	dispatcher *dispatch.Dispatcher,
	domainClient *runtime_domain_client.Client,
	dispatchLockKey int64,
	simulationCooldownSec int,
	stoppingForceCancelSec int,
	predictionTTLDays int,
	predictionTTLKeepRounds int,
	roundAffinityWaitSec int,
	strictTrainModelHandoff bool,
	logger zerolog.Logger,
) *Service {
	if simulationCooldownSec < 0 {
		simulationCooldownSec = 0
	}
	if stoppingForceCancelSec < 0 {
		stoppingForceCancelSec = 0
	}
	if predictionTTLDays < 0 {
		predictionTTLDays = 0
	}
	if predictionTTLKeepRounds < 0 {
		predictionTTLKeepRounds = 0
	}
	if roundAffinityWaitSec < 0 {
		roundAffinityWaitSec = 0
	}
	var (
		pool    *pgxpool.Pool
		queries ControlplaneQuerier
	)
	if repository != nil && repository.Enabled() {
		pool = repository.Pool()
		queries = db.New(pool)
	}

	return &Service{
		pool:                    pool,
		queries:                 queries,
		dispatcher:              dispatcher,
		domainClient:            domainClient,
		dispatchLockKey:         dispatchLockKey,
		simCooldown:             time.Duration(simulationCooldownSec) * time.Second,
		stopForceCancelAfter:    time.Duration(stoppingForceCancelSec) * time.Second,
		predictionTTLDays:       predictionTTLDays,
		predictionTTLKeepRounds: predictionTTLKeepRounds,
		roundAffinityWait:       time.Duration(roundAffinityWaitSec) * time.Second,
		strictModelHandoff:      strictTrainModelHandoff,
		ttlCleanupInterval:      time.Hour,
		logger:                  logger,
	}
}

func (s *Service) dbEnabled() bool {
	return s != nil && s.pool != nil && s.queries != nil
}

func (s *Service) beginTx(ctx context.Context) (pgx.Tx, error) {
	if !s.dbEnabled() {
		return nil, fmt.Errorf("数据库未配置")
	}
	return s.pool.Begin(ctx)
}

func (s *Service) qtx(tx pgx.Tx) *db.Queries {
	return s.queries.WithTx(tx)
}
