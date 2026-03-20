-- name: GetIamRefreshSessionByTokenHash :one
select id, principal_id, family_id, rotated_from, replaced_by, token_hash, user_agent, ip_address, last_seen_at, revoked_at, replay_detected_at, expires_at, created_at, updated_at
from iam_refresh_session
where token_hash = sqlc.arg(token_hash);

-- name: GetIamRefreshSessionByTokenHashForUpdate :one
select id, principal_id, family_id, rotated_from, replaced_by, token_hash, user_agent, ip_address, last_seen_at, revoked_at, replay_detected_at, expires_at, created_at, updated_at
from iam_refresh_session
where token_hash = sqlc.arg(token_hash)
for update;

-- name: ListIamRefreshSessionsByPrincipal :many
select id, principal_id, family_id, rotated_from, replaced_by, token_hash, user_agent, ip_address, last_seen_at, revoked_at, replay_detected_at, expires_at, created_at, updated_at
from iam_refresh_session
where principal_id = sqlc.arg(principal_id)
order by created_at desc;

-- name: CountIamRefreshSessionChildren :one
select count(*)
from iam_refresh_session
where rotated_from = sqlc.arg(session_id);

-- name: CreateIamRefreshSession :one
insert into iam_refresh_session (principal_id, family_id, rotated_from, token_hash, user_agent, ip_address, last_seen_at, expires_at)
values (
    sqlc.arg(principal_id),
    sqlc.arg(family_id),
    sqlc.arg(rotated_from),
    sqlc.arg(token_hash),
    sqlc.arg(user_agent),
    sqlc.arg(ip_address),
    sqlc.arg(last_seen_at),
    sqlc.arg(expires_at)
)
returning id, principal_id, family_id, rotated_from, replaced_by, token_hash, user_agent, ip_address, last_seen_at, revoked_at, replay_detected_at, expires_at, created_at, updated_at;

-- name: MarkIamRefreshSessionRotated :execrows
update iam_refresh_session
set
    replaced_by = sqlc.arg(replaced_by),
    revoked_at = sqlc.arg(revoked_at),
    last_seen_at = sqlc.arg(last_seen_at),
    updated_at = now()
where id = sqlc.arg(id)
  and revoked_at is null
  and replaced_by is null;

-- name: RevokeIamRefreshSessionByTokenHash :execrows
update iam_refresh_session
set
    revoked_at = sqlc.arg(revoked_at),
    updated_at = now()
where token_hash = sqlc.arg(token_hash)
  and revoked_at is null
  and expires_at > sqlc.arg(revoked_at);

-- name: RevokeIamRefreshSessionFamily :exec
update iam_refresh_session
set
    revoked_at = coalesce(revoked_at, sqlc.arg(now)),
    replay_detected_at = coalesce(replay_detected_at, sqlc.arg(now)),
    updated_at = now()
where family_id = sqlc.arg(family_id);

-- name: RevokeIamRefreshSessionsByPrincipal :exec
update iam_refresh_session
set
    revoked_at = coalesce(revoked_at, sqlc.arg(now)),
    updated_at = now()
where principal_id = sqlc.arg(principal_id)
  and revoked_at is null;
