-- +goose Up
-- agent_session 只记录 relay 当前观察到的在线会话归属；
-- 命令真相仍然在 agent_command，session 断开只会让投递失败重试，不会直接改任务状态。
create table agent_session (
    session_id text primary key,
    agent_id text not null references agent (id) on delete cascade,
    relay_id text not null,
    connected_at timestamptz not null,
    last_seen_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint agent_session_agent_id_key unique (agent_id)
);

create index agent_session_relay_id_idx
    on agent_session (relay_id, updated_at desc);

-- +goose Down
drop table if exists agent_session;
