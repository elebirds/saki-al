-- +goose Up
create type runtime_task_kind as enum ('PREDICTION');
create type runtime_task_status as enum (
    'pending',
    'assigned',
    'running',
    'cancel_requested',
    'succeeded',
    'failed',
    'canceled'
);
create type agent_transport_mode as enum ('direct', 'pull', 'relay');
create type agent_command_type as enum ('assign', 'cancel');
create type agent_command_status as enum ('pending', 'claimed', 'acked', 'finished', 'failed', 'expired');

create table runtime_lease (
    name text primary key,
    holder text not null,
    epoch bigint not null,
    lease_until timestamptz not null,
    updated_at timestamptz not null default now()
);

create table runtime_task (
    id uuid primary key,
    task_kind runtime_task_kind not null default 'PREDICTION',
    task_type text not null,
    status runtime_task_status not null default 'pending',
    assigned_agent_id text,
    current_execution_id text,
    attempt integer not null default 0,
    max_attempts integer not null default 1,
    resolved_params jsonb not null default '{}'::jsonb,
    depends_on_task_ids uuid[] not null default '{}'::uuid[],
    leader_epoch bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 关键设计：未发布阶段直接把 runtime 基线改写为 agent/controlplane 最终真相，
-- 新环境不再经历 runtime_executor/runtime_outbox 这一层中间态，避免代码再次回写废弃路径。
create table agent (
    id text primary key,
    version text not null,
    capabilities text[] not null default '{}',
    transport_mode agent_transport_mode not null,
    control_base_url text,
    max_concurrency integer not null default 1,
    running_task_ids text[] not null default '{}',
    status text not null default 'online',
    last_seen_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index agent_last_seen_at_idx
    on agent (last_seen_at desc);

-- task_assignment 把一次 task -> agent 派发单独锚定下来，后续命令重试与恢复都围绕它展开。
create table task_assignment (
    id bigserial primary key,
    task_id uuid not null references runtime_task (id) on delete cascade,
    attempt integer not null,
    agent_id text not null references agent (id),
    execution_id text not null,
    status runtime_task_status not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint task_assignment_execution_id_key unique (execution_id),
    constraint task_assignment_task_attempt_key unique (task_id, attempt)
);

create index task_assignment_agent_created_idx
    on task_assignment (agent_id, created_at desc);

-- agent_command 才是 controlplane 发给 agent 的命令真相；direct/pull/relay 只是不同投递方式。
create table agent_command (
    command_id uuid primary key,
    agent_id text not null references agent (id),
    task_id uuid not null references runtime_task (id) on delete cascade,
    assignment_id bigint not null references task_assignment (id) on delete cascade,
    command_type agent_command_type not null,
    transport_mode agent_transport_mode not null,
    status agent_command_status not null default 'pending',
    payload jsonb not null,
    available_at timestamptz not null default now(),
    expire_at timestamptz not null,
    attempt_count integer not null default 0,
    claim_token uuid,
    claim_until timestamptz,
    acked_at timestamptz,
    finished_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint agent_command_claim_token_key unique (claim_token)
);

create index agent_command_push_due_idx
    on agent_command (available_at, command_id)
    where status = 'pending' and transport_mode in ('direct', 'relay');

create index agent_command_pull_due_idx
    on agent_command (agent_id, available_at, command_id)
    where status = 'pending' and transport_mode = 'pull';

create index agent_command_expire_idx
    on agent_command (expire_at, command_id)
    where status in ('pending', 'claimed', 'acked');

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
drop table if exists agent_command;
drop table if exists task_assignment;
drop table if exists agent;
drop table if exists runtime_task;
drop table if exists runtime_lease;
drop type if exists agent_command_status;
drop type if exists agent_command_type;
drop type if exists agent_transport_mode;
drop type if exists runtime_task_status;
drop type if exists runtime_task_kind;
