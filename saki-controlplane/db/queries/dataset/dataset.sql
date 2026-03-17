-- name: CreateDataset :one
insert into dataset (name, type)
values (sqlc.arg(name), sqlc.arg(type))
returning id, name, type, created_at, updated_at;

-- name: GetDataset :one
select id, name, type, created_at, updated_at
from dataset
where id = sqlc.arg(id);

-- name: CountDatasets :one
select count(*)
from dataset
where sqlc.arg(query_text)::text = ''
   or name ilike '%' || sqlc.arg(query_text)::text || '%';

-- name: ListDatasets :many
select id, name, type, created_at, updated_at
from dataset
where sqlc.arg(query_text)::text = ''
   or name ilike '%' || sqlc.arg(query_text)::text || '%'
order by name, id
limit sqlc.arg(limit_count)
offset sqlc.arg(offset_count);

-- name: UpdateDataset :one
update dataset
set name = sqlc.arg(name),
    type = sqlc.arg(type),
    updated_at = now()
where id = sqlc.arg(id)
returning id, name, type, created_at, updated_at;

-- name: DeleteDataset :execrows
delete from dataset
where id = sqlc.arg(id);
