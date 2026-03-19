package repo

import (
	"context"
	"errors"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
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
	Version        string
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
		Version:        params.Version,
		ID:             params.ID,
		MaxConcurrency: params.MaxConcurrency,
		RunningTaskIds: normalizeTextArray(params.RunningTaskIDs),
		LastSeenAt:     pgtype.Timestamptz{Time: params.LastSeenAt, Valid: true},
	})
	return err
}

func (r *AgentRepo) RegisterAgent(ctx context.Context, agent commands.AgentRecord) (*commands.AgentRecord, error) {
	registered, err := r.Upsert(ctx, UpsertAgentParams{
		ID:             agent.ID,
		Version:        agent.Version,
		Capabilities:   agent.Capabilities,
		TransportMode:  agent.TransportMode,
		ControlBaseURL: agent.ControlBaseURL,
		MaxConcurrency: agent.MaxConcurrency,
		RunningTaskIDs: agent.RunningTaskIDs,
		LastSeenAt:     agent.LastSeenAt,
	})
	if err != nil {
		return nil, err
	}
	return commandsAgentFromRepo(registered), nil
}

func (r *AgentRepo) HeartbeatAgent(ctx context.Context, heartbeat commands.AgentHeartbeat) error {
	return r.Heartbeat(ctx, HeartbeatAgentParams{
		ID:             heartbeat.ID,
		Version:        heartbeat.Version,
		MaxConcurrency: heartbeat.MaxConcurrency,
		RunningTaskIDs: heartbeat.RunningTaskIDs,
		LastSeenAt:     heartbeat.LastSeenAt,
	})
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

func (r *AgentRepo) GetByID(ctx context.Context, agentID string) (*Agent, error) {
	row, err := r.q.GetAgentByID(ctx, agentID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return agentFromModel(row), nil
}

// MarkOfflineAgentsBefore 只把 controlplane 观察到超时未心跳的 agent 标成 offline；
// 真正的任务回收仍由 recovery worker 基于离线事实继续推进。
func (r *AgentRepo) MarkOfflineAgentsBefore(ctx context.Context, offlineBefore time.Time) (int64, error) {
	return r.q.MarkOfflineAgentsBefore(ctx, pgtype.Timestamptz{Time: offlineBefore, Valid: true})
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

func commandsAgentFromRepo(agent *Agent) *commands.AgentRecord {
	if agent == nil {
		return nil
	}
	return &commands.AgentRecord{
		ID:             agent.ID,
		Version:        agent.Version,
		Capabilities:   normalizeTextArray(agent.Capabilities),
		TransportMode:  agent.TransportMode,
		ControlBaseURL: agent.ControlBaseURL,
		MaxConcurrency: agent.MaxConcurrency,
		RunningTaskIDs: normalizeTextArray(agent.RunningTaskIDs),
		Status:         agent.Status,
		LastSeenAt:     agent.LastSeenAt,
	}
}
