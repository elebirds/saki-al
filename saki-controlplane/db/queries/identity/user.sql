-- name: GetIamUserByPrincipalID :one
select principal_id, email, username, full_name, avatar_asset_id, state, created_at, updated_at
from iam_user
where principal_id = sqlc.arg(principal_id);

-- name: GetIamUserByEmail :one
select principal_id, email, username, full_name, avatar_asset_id, state, created_at, updated_at
from iam_user
where lower(email) = lower(sqlc.arg(email));

-- name: GetIamUserByIdentifier :one
select principal_id, email, username, full_name, avatar_asset_id, state, created_at, updated_at
from iam_user
where lower(email) = lower(sqlc.arg(identifier))
   or username = sqlc.arg(identifier)
order by case when lower(email) = lower(sqlc.arg(identifier)) then 0 else 1 end
limit 1;

-- name: CreateIamUser :one
insert into iam_user (principal_id, email, username, full_name, avatar_asset_id)
values (sqlc.arg(principal_id), sqlc.arg(email), sqlc.arg(username), sqlc.arg(full_name), sqlc.arg(avatar_asset_id))
returning principal_id, email, username, full_name, avatar_asset_id, state, created_at, updated_at;

-- name: UpdateIamUserProfile :exec
update iam_user
set email = sqlc.arg(email), username = sqlc.arg(username), full_name = sqlc.arg(full_name), avatar_asset_id = sqlc.arg(avatar_asset_id), updated_at = now()
where principal_id = sqlc.arg(principal_id);
