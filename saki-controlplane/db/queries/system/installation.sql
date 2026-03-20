-- name: GetSystemInstallation :one
select id, installation_key, install_state, metadata, setup_at, setup_by_principal_id, created_at, updated_at
from system_installation
where installation_key = 'primary';

-- name: UpsertSystemInstallation :one
insert into system_installation (installation_key, install_state, metadata, setup_at, setup_by_principal_id)
values (
    'primary',
    sqlc.arg(install_state),
    sqlc.arg(metadata),
    sqlc.arg(setup_at),
    sqlc.arg(setup_by_principal_id)
)
on conflict (installation_key) do update
set install_state = excluded.install_state,
    metadata = excluded.metadata,
    setup_at = excluded.setup_at,
    setup_by_principal_id = excluded.setup_by_principal_id,
    updated_at = now()
returning id, installation_key, install_state, metadata, setup_at, setup_by_principal_id, created_at, updated_at;
