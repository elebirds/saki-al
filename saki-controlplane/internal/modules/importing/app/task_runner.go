package app

import (
	"context"
	"encoding/json"
	"errors"

	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

type SampleStore interface {
	Get(ctx context.Context, sampleID uuid.UUID) (*annotationrepo.Sample, error)
}

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
	samples     SampleStore
	annotations AnnotationCreateStore
	tasks       MutableImportTaskStore
}

func NewProjectAnnotationsTaskRunner(samples SampleStore, annotations AnnotationCreateStore, tasks MutableImportTaskStore) *ProjectAnnotationsTaskRunner {
	return &ProjectAnnotationsTaskRunner{
		samples:     samples,
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
		if r.samples != nil {
			sample, err := r.samples.Get(ctx, entry.ResolvedSampleID)
			if err != nil {
				return err
			}
			if sample == nil {
				return errors.New("sample not found")
			}
			if sample.DatasetID != manifest.DatasetID {
				return errors.New("sample dataset mismatch")
			}
		}
		if _, err := r.annotations.Create(ctx, annotationrepo.CreateAnnotationParams{
			ProjectID:      manifest.ProjectID,
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
