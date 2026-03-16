-- name: CreateAnnotation :one
insert into annotation (
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
returning id, sample_id, group_id, label_id, view, annotation_type, geometry, attrs, source, is_generated, created_at;

-- name: ListAnnotationsBySample :many
select id, sample_id, group_id, label_id, view, annotation_type, geometry, attrs, source, is_generated, created_at
from annotation
where sample_id = sqlc.arg(sample_id)
order by created_at, id;
