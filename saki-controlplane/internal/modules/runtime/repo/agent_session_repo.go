package repo

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type AgentSession struct {
	AgentID     string
	RelayID     string
	SessionID   string
	ConnectedAt time.Time
	LastSeenAt  time.Time
}

type UpsertAgentSessionParams struct {
	AgentID     string
	RelayID     string
	SessionID   string
	ConnectedAt time.Time
	LastSeenAt  time.Time
}

// AgentSessionRepo 只维护 relay 观察到的在线流会话，不把它当成命令或任务状态真相。
type AgentSessionRepo struct {
	pool *pgxpool.Pool
}

func NewAgentSessionRepo(pool *pgxpool.Pool) *AgentSessionRepo {
	return &AgentSessionRepo{pool: pool}
}

func (r *AgentSessionRepo) Upsert(ctx context.Context, params UpsertAgentSessionParams) (*AgentSession, error) {
	if r == nil || r.pool == nil {
		return nil, nil
	}

	row := r.pool.QueryRow(ctx, `
insert into agent_session (
    session_id,
    agent_id,
    relay_id,
    connected_at,
    last_seen_at,
    updated_at
)
values ($1, $2, $3, $4, $5, now())
on conflict (agent_id) do update
set session_id = excluded.session_id,
    relay_id = excluded.relay_id,
    connected_at = excluded.connected_at,
    last_seen_at = excluded.last_seen_at,
    updated_at = now()
returning agent_id, relay_id, session_id, connected_at, last_seen_at
`, params.SessionID, params.AgentID, params.RelayID, params.ConnectedAt, params.LastSeenAt)

	return scanAgentSession(row)
}

func (r *AgentSessionRepo) GetByAgentID(ctx context.Context, agentID string) (*AgentSession, error) {
	if r == nil || r.pool == nil {
		return nil, nil
	}

	row := r.pool.QueryRow(ctx, `
select agent_id, relay_id, session_id, connected_at, last_seen_at
from agent_session
where agent_id = $1
`, agentID)
	session, err := scanAgentSession(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return session, err
}

func (r *AgentSessionRepo) Delete(ctx context.Context, sessionID string) error {
	if r == nil || r.pool == nil {
		return nil
	}
	_, err := r.pool.Exec(ctx, `
delete from agent_session
where session_id = $1
`, sessionID)
	return err
}

func (r *AgentSessionRepo) Touch(ctx context.Context, sessionID string, seenAt time.Time) error {
	if r == nil || r.pool == nil {
		return nil
	}
	_, err := r.pool.Exec(ctx, `
update agent_session
set last_seen_at = $2,
    updated_at = now()
where session_id = $1
`, sessionID, seenAt)
	return err
}

type agentSessionScanner interface {
	Scan(dest ...any) error
}

func scanAgentSession(row agentSessionScanner) (*AgentSession, error) {
	var session AgentSession
	if err := row.Scan(
		&session.AgentID,
		&session.RelayID,
		&session.SessionID,
		&session.ConnectedAt,
		&session.LastSeenAt,
	); err != nil {
		return nil, err
	}
	return &session, nil
}
