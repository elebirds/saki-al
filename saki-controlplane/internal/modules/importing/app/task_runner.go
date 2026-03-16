package app

import (
	"context"
	"encoding/json"

	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

type AnnotationCreateStore interface {
	Create(ctx context.Context, params annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error)
}

type MutableImportTaskStore interface {
	AppendEvent(ctx context.Context, params importrepo.AppendTaskEventParams) (*importrepo.ImportTaskEvent, error)
	MarkRunning(ctx context.Context, taskID uuid.UUID) error
	MarkCompleted(ctx context.Context, taskID uuid.UUID, result []byte) error
	MarkFailed(ctx context.Context, taskID uuid.UUID, result []byte) error
}

type ProjectAnnotationsTaskRunner struct {
	annotations AnnotationCreateStore
	tasks       MutableImportTaskStore
}

func NewProjectAnnotationsTaskRunner(annotations AnnotationCreateStore, tasks MutableImportTaskStore) *ProjectAnnotationsTaskRunner {
	return &ProjectAnnotationsTaskRunner{
		annotations: annotations,
		tasks:       tasks,
	}
}

func (r *ProjectAnnotationsTaskRunner) Run(ctx context.Context, taskID uuid.UUID, manifest PreviewManifest) error {
	if err := r.tasks.MarkRunning(ctx, taskID); err != nil {
		return err
	}
	if _, err := r.tasks.AppendEvent(ctx, importrepo.AppendTaskEventParams{
		TaskID:  taskID,
		Event:   "start",
		Phase:   "project_annotations_execute",
		Payload: []byte(`{"message":"task started"}`),
	}); err != nil {
		return err
	}
	if _, err := r.tasks.AppendEvent(ctx, importrepo.AppendTaskEventParams{
		TaskID:  taskID,
		Event:   "phase",
		Phase:   "apply_annotations",
		Payload: []byte(`{"message":"applying annotations"}`),
	}); err != nil {
		return err
	}

	for _, entry := range manifest.MatchedAnnotations {
		if _, err := r.annotations.Create(ctx, annotationrepo.CreateAnnotationParams{
			SampleID:       entry.ResolvedSampleID,
			GroupID:        entry.GroupID,
			LabelID:        entry.LabelID,
			View:           entry.View,
			AnnotationType: entry.AnnotationType,
			Geometry:       entry.Geometry,
			Attrs:          []byte(`{}`),
			Source:         entry.Source,
			IsGenerated:    false,
		}); err != nil {
			result, marshalErr := json.Marshal(map[string]any{
				"status": "failed",
				"error":  err.Error(),
			})
			if marshalErr != nil {
				return marshalErr
			}
			_, _ = r.tasks.AppendEvent(ctx, importrepo.AppendTaskEventParams{
				TaskID:  taskID,
				Event:   "error",
				Phase:   "apply_annotations",
				Payload: result,
			})
			if markErr := r.tasks.MarkFailed(ctx, taskID, result); markErr != nil {
				return markErr
			}
			return err
		}
	}

	result, err := json.Marshal(map[string]any{
		"status":              "succeeded",
		"created_annotations": len(manifest.MatchedAnnotations),
	})
	if err != nil {
		return err
	}
	if _, err := r.tasks.AppendEvent(ctx, importrepo.AppendTaskEventParams{
		TaskID:  taskID,
		Event:   "complete",
		Phase:   "project_annotations_execute",
		Payload: result,
	}); err != nil {
		return err
	}
	return r.tasks.MarkCompleted(ctx, taskID, result)
}
