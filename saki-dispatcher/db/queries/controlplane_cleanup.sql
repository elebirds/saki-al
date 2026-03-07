-- name: DeletePredictionCandidates :execrows
DELETE FROM task_candidate_item c
USING step s
JOIN round r ON r.id = s.round_id
WHERE c.task_id = s.task_id
  AND s.step_type = 'SCORE'::steptype
  AND s.task_id IS NOT NULL
  AND COALESCE(s.ended_at, s.updated_at, s.created_at) < sqlc.arg(cutoff)
  AND (
    SELECT COUNT(*)::int
    FROM round r2
    WHERE r2.loop_id = r.loop_id
      AND r2.round_index >= r.round_index
  ) > sqlc.arg(keep_rounds)::int;

-- name: DeletePredictionEvents :execrows
DELETE FROM task_event e
USING step s
JOIN round r ON r.id = s.round_id
WHERE e.task_id = s.task_id
  AND s.step_type = 'SCORE'::steptype
  AND s.task_id IS NOT NULL
  AND COALESCE(s.ended_at, s.updated_at, s.created_at) < sqlc.arg(cutoff)
  AND (
    SELECT COUNT(*)::int
    FROM round r2
    WHERE r2.loop_id = r.loop_id
      AND r2.round_index >= r.round_index
  ) > sqlc.arg(keep_rounds)::int
  AND e.event_type = ANY(sqlc.arg(event_types)::text[]);

-- name: DeletePredictionMetrics :execrows
DELETE FROM task_metric_point m
USING step s
JOIN round r ON r.id = s.round_id
WHERE m.task_id = s.task_id
  AND s.step_type = 'SCORE'::steptype
  AND s.task_id IS NOT NULL
  AND COALESCE(s.ended_at, s.updated_at, s.created_at) < sqlc.arg(cutoff)
  AND (
    SELECT COUNT(*)::int
    FROM round r2
    WHERE r2.loop_id = r.loop_id
      AND r2.round_index >= r.round_index
  ) > sqlc.arg(keep_rounds)::int;
