-- name: GetIamUserByPrincipalID :one
select principal_id, email, username, full_name, avatar_asset_id, state, created_at, updated_at
from iam_user
where principal_id = sqlc.arg(principal_id);

-- name: CountIamUsers :one
select count(*)
from iam_user;

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

-- name: ListIamUsersForAdmin :many
select
    u.principal_id,
    u.email,
    u.username,
    u.full_name,
    u.avatar_asset_id,
    u.state,
    u.created_at,
    u.updated_at,
    p.status as principal_status,
    coalesce(bool_or(c.must_change_password), false)::boolean as must_change_password
from iam_user u
join iam_principal p on p.id = u.principal_id
left join iam_password_credential c on c.principal_id = u.principal_id
group by
    u.principal_id,
    u.email,
    u.username,
    u.full_name,
    u.avatar_asset_id,
    u.state,
    u.created_at,
    u.updated_at,
    p.status
order by u.created_at desc, u.principal_id
limit sqlc.arg(limit_count)
offset sqlc.arg(offset_count);

-- name: UpdateIamUserProfile :exec
update iam_user
set email = sqlc.arg(email), username = sqlc.arg(username), full_name = sqlc.arg(full_name), avatar_asset_id = sqlc.arg(avatar_asset_id), updated_at = now()
where principal_id = sqlc.arg(principal_id);
