-- name: GetProject :one
select id, name, created_at, updated_at
from project
where id = sqlc.arg(id);
