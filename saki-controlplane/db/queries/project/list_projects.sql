-- name: ListProjects :many
select id, name, created_at, updated_at
from project
order by name;
