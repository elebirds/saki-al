package app

import (
	"context"
	"encoding/json"
	"testing"

	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

func TestProjectAnnotationsTaskRunnerCreatesAnnotationsAndEvents(t *testing.T) {
	t.Parallel()

	taskID := uuid.New()
	sampleID := uuid.New()
	taskStore := &fakeMutableTaskStore{}
	annotationStore := &fakeAnnotationStore{}
	runner := NewProjectAnnotationsTaskRunner(annotationStore, taskStore)

	err := runner.Run(context.Background(), taskID, PreviewManifest{
		MatchedAnnotations: []MatchedAnnotationEntry{
			{
				AnnotationID:     "ann-1",
				ResolvedSampleID: sampleID,
				GroupID:          "ann-1",
				LabelID:          "car",
				LabelName:        "car",
				View:             "default",
				AnnotationType:   "rect",
				Geometry:         json.RawMessage(`{"rect":{"x":10,"y":20,"width":100,"height":50}}`),
				Source:           "imported",
			},
		},
	})
	if err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	if got, want := len(annotationStore.created), 1; got != want {
		t.Fatalf("created annotations len got %d want %d", got, want)
	}
	if got, want := annotationStore.created[0].SampleID, sampleID; got != want {
		t.Fatalf("created annotation sample_id got %s want %s", got, want)
	}
	if got, want := len(taskStore.events), 3; got != want {
		t.Fatalf("task events len got %d want %d", got, want)
	}
	if got, want := taskStore.status, "succeeded"; got != want {
		t.Fatalf("task status got %q want %q", got, want)
	}
	if len(taskStore.result) == 0 {
		t.Fatal("expected task result to be written")
	}
}

type fakeAnnotationStore struct {
	created []annotationrepo.CreateAnnotationParams
}

func (s *fakeAnnotationStore) Create(ctx context.Context, params annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error) {
	s.created = append(s.created, params)
	return &annotationrepo.Annotation{
		ID:             uuid.New(),
		SampleID:       params.SampleID,
		GroupID:        params.GroupID,
		LabelID:        params.LabelID,
		View:           params.View,
		AnnotationType: params.AnnotationType,
		Geometry:       params.Geometry,
		Attrs:          params.Attrs,
		Source:         params.Source,
		IsGenerated:    params.IsGenerated,
	}, nil
}

type fakeMutableTaskStore struct {
	events []importrepo.AppendTaskEventParams
	status string
	result []byte
}

func (s *fakeMutableTaskStore) AppendEvent(ctx context.Context, params importrepo.AppendTaskEventParams) (*importrepo.ImportTaskEvent, error) {
	s.events = append(s.events, params)
	return &importrepo.ImportTaskEvent{Seq: int64(len(s.events)), TaskID: params.TaskID, Event: params.Event, Phase: params.Phase, Payload: params.Payload}, nil
}

func (s *fakeMutableTaskStore) MarkRunning(ctx context.Context, taskID uuid.UUID) error {
	s.status = "running"
	return nil
}

func (s *fakeMutableTaskStore) MarkCompleted(ctx context.Context, taskID uuid.UUID, result []byte) error {
	s.status = "succeeded"
	s.result = result
	return nil
}

func (s *fakeMutableTaskStore) MarkFailed(ctx context.Context, taskID uuid.UUID, result []byte) error {
	s.status = "failed"
	s.result = result
	return nil
}
