-- name: GetProject :one
select id, name
from project
where id = sqlc.arg(id);
