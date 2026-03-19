package repo

import (
	"context"
	"slices"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type Agent struct {
	ID             string
	Version        string
	Capabilities   []string
	TransportMode  string
	ControlBaseURL string
	MaxConcurrency int32
	RunningTaskIDs []string
	Status         string
	LastSeenAt     time.Time
}

type UpsertAgentParams struct {
	ID             string
	Version        string
	Capabilities   []string
	TransportMode  string
	ControlBaseURL string
	MaxConcurrency int32
	RunningTaskIDs []string
	LastSeenAt     time.Time
}

type HeartbeatAgentParams struct {
	ID             string
	MaxConcurrency int32
	RunningTaskIDs []string
	LastSeenAt     time.Time
}

// AgentRepo 只维护 controlplane 已经观察到的 agent 事实，不承担连接态真相。
type AgentRepo struct {
	q *sqlcdb.Queries
}

func NewAgentRepo(pool *pgxpool.Pool) *AgentRepo {
	return newAgentRepo(sqlcdb.New(pool))
}

func newAgentRepo(q *sqlcdb.Queries) *AgentRepo {
	return &AgentRepo{q: q}
}

func (r *AgentRepo) Upsert(ctx context.Context, params UpsertAgentParams) (*Agent, error) {
	row, err := r.q.UpsertAgent(ctx, sqlcdb.UpsertAgentParams{
		ID:             params.ID,
		Version:        params.Version,
		Capabilities:   normalizeTextArray(params.Capabilities),
		TransportMode:  sqlcdb.AgentTransportMode(params.TransportMode),
		ControlBaseUrl: nullableText(params.ControlBaseURL),
		MaxConcurrency: params.MaxConcurrency,
		RunningTaskIds: normalizeTextArray(params.RunningTaskIDs),
		LastSeenAt:     pgtype.Timestamptz{Time: params.LastSeenAt, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	return agentFromModel(row), nil
}

func (r *AgentRepo) Heartbeat(ctx context.Context, params HeartbeatAgentParams) error {
	_, err := r.q.HeartbeatAgent(ctx, sqlcdb.HeartbeatAgentParams{
		ID:             params.ID,
		MaxConcurrency: params.MaxConcurrency,
		RunningTaskIds: normalizeTextArray(params.RunningTaskIDs),
		LastSeenAt:     pgtype.Timestamptz{Time: params.LastSeenAt, Valid: true},
	})
	return err
}

func (r *AgentRepo) List(ctx context.Context) ([]Agent, error) {
	rows, err := r.q.ListAgents(ctx)
	if err != nil {
		return nil, err
	}

	agents := make([]Agent, 0, len(rows))
	for _, row := range rows {
		agents = append(agents, *agentFromModel(row))
	}
	return agents, nil
}

func normalizeTextArray(items []string) []string {
	if items == nil {
		return []string{}
	}
	return slices.Clone(items)
}

func agentFromModel(row sqlcdb.Agent) *Agent {
	return &Agent{
		ID:             row.ID,
		Version:        row.Version,
		Capabilities:   normalizeTextArray(row.Capabilities),
		TransportMode:  string(row.TransportMode),
		ControlBaseURL: textValue(row.ControlBaseUrl),
		MaxConcurrency: row.MaxConcurrency,
		RunningTaskIDs: normalizeTextArray(row.RunningTaskIds),
		Status:         row.Status,
		LastSeenAt:     row.LastSeenAt.Time,
	}
}
