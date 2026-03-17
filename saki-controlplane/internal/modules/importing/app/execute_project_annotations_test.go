package app

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	"github.com/google/uuid"
)

func TestExecuteProjectAnnotationsRejectsBlockingPreview(t *testing.T) {
	t.Parallel()

	previewToken := "preview-1"
	projectID := uuid.New()
	datasetID := uuid.New()
	useCase := NewExecuteProjectAnnotationsUseCase(
		fakeProjectStore{
			links: map[string]*projectrepo.ProjectDatasetLink{
				projectDatasetKey(projectID, datasetID): {
					ProjectID: projectID,
					DatasetID: datasetID,
				},
			},
		},
		fakePreviewLoader{
			manifest: &importrepo.PreviewManifest{
				Token:     previewToken,
				ProjectID: projectID,
				DatasetID: datasetID,
				Manifest: mustMarshalJSON(t, PreviewManifest{
					ProjectID: projectID,
					DatasetID: datasetID,
					Errors:    []PrepareIssue{{Code: "UNSUPPORTED_GEOMETRY", Message: "polygon unsupported"}},
				}),
			},
		},
		&fakeImportTaskStore{},
		&fakeTaskRunner{},
	)

	_, err := useCase.Execute(context.Background(), ExecuteProjectAnnotationsInput{
		ProjectID:    projectID,
		DatasetID:    datasetID,
		PreviewToken: previewToken,
		UserID:       uuid.New(),
	})
	if !errors.Is(err, ErrBlockingPreviewManifest) {
		t.Fatalf("expected ErrBlockingPreviewManifest, got %v", err)
	}
}

func TestExecuteProjectAnnotationsCreatesTaskAndRunsRunner(t *testing.T) {
	t.Parallel()

	previewToken := "preview-1"
	projectID := uuid.New()
	datasetID := uuid.New()
	userID := uuid.New()
	resourceID := projectID

	runner := &fakeTaskRunner{}
	taskStore := &fakeImportTaskStore{}
	useCase := NewExecuteProjectAnnotationsUseCase(
		fakeProjectStore{
			links: map[string]*projectrepo.ProjectDatasetLink{
				projectDatasetKey(projectID, datasetID): {
					ProjectID: projectID,
					DatasetID: datasetID,
				},
			},
		},
		fakePreviewLoader{
			manifest: &importrepo.PreviewManifest{
				Token:     previewToken,
				ProjectID: projectID,
				DatasetID: datasetID,
				Manifest: mustMarshalJSON(t, PreviewManifest{
					Mode:            "project_annotations",
					ProjectID:       projectID,
					DatasetID:       datasetID,
					UploadSessionID: uuid.New(),
					FormatProfile:   "coco",
					MatchedAnnotations: []MatchedAnnotationEntry{
						{AnnotationID: "ann-1", ResolvedSampleID: uuid.New(), GroupID: "ann-1", LabelID: "car", LabelName: "car", View: "default", AnnotationType: "rect", Geometry: json.RawMessage(`{"rect":{"x":10,"y":20,"width":100,"height":50}}`), Source: "imported"},
					},
				}),
			},
		},
		taskStore,
		runner,
	)

	task, err := useCase.Execute(context.Background(), ExecuteProjectAnnotationsInput{
		ProjectID:    projectID,
		DatasetID:    datasetID,
		PreviewToken: previewToken,
		UserID:       userID,
	})
	if err != nil {
		t.Fatalf("Execute failed: %v", err)
	}
	if task == nil {
		t.Fatal("expected task")
	}
	if got, want := task.UserID, userID; got != want {
		t.Fatalf("task user_id got %s want %s", got, want)
	}
	if got, want := task.ResourceID, resourceID; got != want {
		t.Fatalf("task resource_id got %s want %s", got, want)
	}
	if !runner.called {
		t.Fatal("expected runner to be invoked")
	}
	if got, want := runner.lastManifest.DatasetID, datasetID; got != want {
		t.Fatalf("runner manifest dataset_id got %s want %s", got, want)
	}
}

type fakePreviewLoader struct {
	manifest *importrepo.PreviewManifest
}

func (s fakePreviewLoader) Get(ctx context.Context, token string) (*importrepo.PreviewManifest, error) {
	return s.manifest, nil
}

type fakeImportTaskStore struct {
	created *importrepo.ImportTask
}

func (s *fakeImportTaskStore) Create(ctx context.Context, params importrepo.CreateTaskParams) (*importrepo.ImportTask, error) {
	s.created = &importrepo.ImportTask{
		ID:           params.ID,
		UserID:       params.UserID,
		Mode:         params.Mode,
		ResourceType: params.ResourceType,
		ResourceID:   params.ResourceID,
		Status:       "queued",
		Payload:      params.Payload,
	}
	return s.created, nil
}

type fakeTaskRunner struct {
	called       bool
	lastManifest PreviewManifest
}

func (r *fakeTaskRunner) Run(ctx context.Context, taskID uuid.UUID, manifest PreviewManifest) error {
	r.called = true
	r.lastManifest = manifest
	return nil
}

func mustMarshalJSON(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("marshal json: %v", err)
	}
	return raw
}
