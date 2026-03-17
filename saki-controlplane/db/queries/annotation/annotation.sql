-- name: CreateAnnotation :one
insert into annotation (
    project_id,
    sample_id,
    group_id,
    label_id,
    view,
    annotation_type,
    geometry,
    attrs,
    source,
    is_generated
)
values (
    sqlc.arg(project_id),
    sqlc.arg(sample_id),
    sqlc.arg(group_id),
    sqlc.arg(label_id),
    sqlc.arg(view),
    sqlc.arg(annotation_type),
    sqlc.arg(geometry),
    sqlc.arg(attrs),
    sqlc.arg(source),
    sqlc.arg(is_generated)
)
returning id, project_id, sample_id, group_id, label_id, view, annotation_type, geometry, attrs, source, is_generated, created_at;

-- name: ListAnnotationsByProjectSample :many
select id, project_id, sample_id, group_id, label_id, view, annotation_type, geometry, attrs, source, is_generated, created_at
from annotation
where project_id = sqlc.arg(project_id)
  and sample_id = sqlc.arg(sample_id)
order by created_at, id;
