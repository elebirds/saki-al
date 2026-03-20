-- name: GetSystemInstallation :one
select id, installation_key, metadata, created_at, updated_at
from system_installation
order by created_at desc
limit 1;

-- name: UpsertSystemInstallation :one
insert into system_installation (installation_key, metadata)
values (sqlc.arg(installation_key), sqlc.arg(metadata))
on conflict (installation_key) do update
set metadata = excluded.metadata,
    updated_at = now()
returning id, installation_key, metadata, created_at, updated_at;
