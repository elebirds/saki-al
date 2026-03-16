-- name: ListProjects :many
select id, name
from project
order by name;
