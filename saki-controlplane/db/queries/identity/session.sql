-- name: GetIamRefreshSessionByTokenHash :one
select id, principal_id, token_hash, user_agent, ip_address, last_seen_at, expires_at, created_at, updated_at
from iam_refresh_session
where token_hash = sqlc.arg(token_hash);

-- name: ListIamRefreshSessionsByPrincipal :many
select id, principal_id, token_hash, user_agent, ip_address, last_seen_at, expires_at, created_at, updated_at
from iam_refresh_session
where principal_id = sqlc.arg(principal_id)
order by created_at desc;

-- name: CreateIamRefreshSession :one
insert into iam_refresh_session (principal_id, token_hash, user_agent, ip_address, last_seen_at, expires_at)
values (sqlc.arg(principal_id), sqlc.arg(token_hash), sqlc.arg(user_agent), sqlc.arg(ip_address), sqlc.arg(last_seen_at), sqlc.arg(expires_at))
returning id, principal_id, token_hash, user_agent, ip_address, last_seen_at, expires_at, created_at, updated_at;

-- name: ConsumeActiveIamRefreshSessionByTokenHash :one
delete from iam_refresh_session
where token_hash = sqlc.arg(token_hash)
  and expires_at > sqlc.arg(now)
returning id, principal_id, token_hash, user_agent, ip_address, last_seen_at, expires_at, created_at, updated_at;

-- name: DeleteIamRefreshSession :exec
delete from iam_refresh_session
where id = sqlc.arg(id);
