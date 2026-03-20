-- name: ListSystemSettings :many
select id, installation_id, key, value, created_at, updated_at
from system_setting
where installation_id = sqlc.arg(installation_id)
order by key;

-- name: GetSystemSettingByKey :one
select id, installation_id, key, value, created_at, updated_at
from system_setting
where installation_id = sqlc.arg(installation_id)
  and key = sqlc.arg(key);

-- name: UpsertSystemSetting :one
insert into system_setting (installation_id, key, value)
values (sqlc.arg(installation_id), sqlc.arg(key), sqlc.arg(value))
on conflict (installation_id, key) do update
set value = excluded.value,
    updated_at = now()
returning id, installation_id, key, value, created_at, updated_at;
