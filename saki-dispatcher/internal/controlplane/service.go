package controlplane

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
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
	ListDispatchLaneHeadCandidates(ctx context.Context, limitCount int32) ([]db.ListDispatchLaneHeadCandidatesRow, error)
	WithTx(tx pgx.Tx) *db.Queries
}

type Service struct {
	pool                        *pgxpool.Pool
	queries                     ControlplaneQuerier
	dispatcher                  *dispatch.Dispatcher
	domainClient                *runtime_domain_client.Client
	dispatchLockKey             int64
	simCooldown                 time.Duration
	stopForceCancelAfter        time.Duration
	heartbeatTimeout            time.Duration
	inFlightPreRunTimeout       time.Duration
	inFlightRunningTimeout      time.Duration
	terminalResultRecoveryGrace time.Duration
	predictionTTLDays           int
	predictionTTLKeepRounds     int
	roundAffinityWait           time.Duration
	strictModelHandoff          bool
	lastTTLCleanupAt            time.Time
	ttlCleanupInterval          time.Duration
	logger                      zerolog.Logger
	laneStateMu                 sync.Mutex
	laneState                   map[string]dispatchLaneState
}

type dispatchLaneState struct {
	SkipRounds     int
	LastDispatchAt time.Time
	LastSeenAt     time.Time
}

func NewService(
	repository *repo.RuntimeRepo,
	dispatcher *dispatch.Dispatcher,
	domainClient *runtime_domain_client.Client,
	dispatchLockKey int64,
	simulationCooldownSec int,
	stoppingForceCancelSec int,
	heartbeatTimeoutSec int,
	inFlightPreRunTimeoutSec int,
	inFlightRunningTimeoutSec int,
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
	if heartbeatTimeoutSec <= 0 {
		heartbeatTimeoutSec = 30
	}
	if inFlightPreRunTimeoutSec <= 0 {
		inFlightPreRunTimeoutSec = 120
	}
	if inFlightRunningTimeoutSec <= 0 {
		inFlightRunningTimeoutSec = 120
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
		pool:                        pool,
		queries:                     queries,
		dispatcher:                  dispatcher,
		domainClient:                domainClient,
		dispatchLockKey:             dispatchLockKey,
		simCooldown:                 time.Duration(simulationCooldownSec) * time.Second,
		stopForceCancelAfter:        time.Duration(stoppingForceCancelSec) * time.Second,
		heartbeatTimeout:            time.Duration(heartbeatTimeoutSec) * time.Second,
		inFlightPreRunTimeout:       time.Duration(inFlightPreRunTimeoutSec) * time.Second,
		inFlightRunningTimeout:      time.Duration(inFlightRunningTimeoutSec) * time.Second,
		terminalResultRecoveryGrace: 2 * time.Minute,
		predictionTTLDays:           predictionTTLDays,
		predictionTTLKeepRounds:     predictionTTLKeepRounds,
		roundAffinityWait:           time.Duration(roundAffinityWaitSec) * time.Second,
		strictModelHandoff:          strictTrainModelHandoff,
		ttlCleanupInterval:          time.Hour,
		logger:                      logger,
		laneState:                   map[string]dispatchLaneState{},
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

func normalizeMaintenanceMode(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case maintenanceModeDrain:
		return maintenanceModeDrain
	case maintenanceModePauseNow:
		return maintenanceModePauseNow
	default:
		return maintenanceModeNormal
	}
}

func normalizeMaintenanceModeValue(raw any) string {
	switch value := raw.(type) {
	case string:
		return normalizeMaintenanceMode(value)
	case []byte:
		return normalizeMaintenanceMode(string(value))
	default:
		return maintenanceModeNormal
	}
}

func (s *Service) getRuntimeMaintenanceMode(ctx context.Context) (string, error) {
	if !s.dbEnabled() {
		return maintenanceModeNormal, nil
	}
	value, err := s.queries.GetRuntimeMaintenanceMode(ctx)
	if err != nil {
		return "", err
	}
	return normalizeMaintenanceModeValue(value), nil
}

func (s *Service) getRuntimeMaintenanceModeTx(ctx context.Context, tx pgx.Tx) (string, error) {
	if !s.dbEnabled() {
		return maintenanceModeNormal, nil
	}
	value, err := s.qtx(tx).GetRuntimeMaintenanceMode(ctx)
	if err != nil {
		return "", err
	}
	return normalizeMaintenanceModeValue(value), nil
}

func (s *Service) ValidateCurrentExecutionID(ctx context.Context, taskID uuid.UUID, executionID uuid.UUID) (bool, error) {
	if !s.dbEnabled() {
		return true, nil
	}
	if taskID == uuid.Nil || executionID == uuid.Nil {
		return false, nil
	}
	currentExecutionID, err := s.queries.GetTaskCurrentExecutionID(ctx, taskID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return false, nil
		}
		return false, err
	}
	return currentExecutionID == executionID, nil
}
