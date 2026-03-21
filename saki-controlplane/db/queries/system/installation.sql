-- name: GetSystemInstallation :one
select id, installation_key, initialization_state, metadata, initialized_at, initialized_by_principal_id, created_at, updated_at
from system_installation
where installation_key = 'primary';

-- name: UpsertSystemInstallation :one
insert into system_installation (installation_key, initialization_state, metadata, initialized_at, initialized_by_principal_id)
values (
    'primary',
    sqlc.arg(initialization_state),
    sqlc.arg(metadata),
    sqlc.arg(initialized_at),
    sqlc.arg(initialized_by_principal_id)
)
on conflict (installation_key) do update
set initialization_state = excluded.initialization_state,
    metadata = excluded.metadata,
    initialized_at = excluded.initialized_at,
    initialized_by_principal_id = excluded.initialized_by_principal_id,
    updated_at = now()
returning id, installation_key, initialization_state, metadata, initialized_at, initialized_by_principal_id, created_at, updated_at;
