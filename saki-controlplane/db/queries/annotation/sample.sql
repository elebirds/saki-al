-- name: CreateSample :one
insert into sample (project_id, dataset_type, meta)
values (sqlc.arg(project_id), sqlc.arg(dataset_type), sqlc.arg(meta))
returning id, project_id, dataset_type, meta, created_at;

-- name: GetSample :one
select id, project_id, dataset_type, meta, created_at
from sample
where id = sqlc.arg(id);
