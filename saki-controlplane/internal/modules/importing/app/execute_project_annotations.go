package app

import (
	"context"
	"encoding/json"
	"errors"

	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	"github.com/google/uuid"
)

var ErrBlockingPreviewManifest = errors.New("preview manifest has blocking errors")

type PreviewManifestLoader interface {
	Get(ctx context.Context, token string) (*importrepo.PreviewManifest, error)
}

type ProjectDatasetLinkStore interface {
	GetProjectDatasetLink(ctx context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error)
}

type ImportTaskCreator interface {
	Create(ctx context.Context, params importrepo.CreateTaskParams) (*importrepo.ImportTask, error)
}

type ImportTaskRunner interface {
	Run(ctx context.Context, taskID uuid.UUID, manifest PreviewManifest) error
}

type ExecuteProjectAnnotationsInput struct {
	ProjectID    uuid.UUID
	DatasetID    uuid.UUID
	PreviewToken string
	UserID       uuid.UUID
}

type ExecuteProjectAnnotationsUseCase struct {
	projects ProjectDatasetLinkStore
	previews PreviewManifestLoader
	tasks    ImportTaskCreator
	runner   ImportTaskRunner
}

func NewExecuteProjectAnnotationsUseCase(projects ProjectDatasetLinkStore, previews PreviewManifestLoader, tasks ImportTaskCreator, runner ImportTaskRunner) *ExecuteProjectAnnotationsUseCase {
	return &ExecuteProjectAnnotationsUseCase{
		projects: projects,
		previews: previews,
		tasks:    tasks,
		runner:   runner,
	}
}

func (u *ExecuteProjectAnnotationsUseCase) Execute(ctx context.Context, input ExecuteProjectAnnotationsInput) (*importrepo.ImportTask, error) {
	preview, err := u.previews.Get(ctx, input.PreviewToken)
	if err != nil {
		return nil, err
	}
	if preview == nil {
		return nil, errors.New("preview manifest not found")
	}
	if preview.ProjectID != input.ProjectID || preview.DatasetID != input.DatasetID {
		return nil, errors.New("preview manifest scope mismatch")
	}
	if u.projects != nil {
		link, err := u.projects.GetProjectDatasetLink(ctx, input.ProjectID, input.DatasetID)
		if err != nil {
			return nil, err
		}
		if link == nil {
			return nil, errors.New("dataset is not linked to project")
		}
	}

	var manifest PreviewManifest
	if err := json.Unmarshal(preview.Manifest, &manifest); err != nil {
		return nil, err
	}
	if manifest.ProjectID != input.ProjectID || manifest.DatasetID != input.DatasetID {
		return nil, errors.New("preview manifest payload scope mismatch")
	}
	if len(manifest.Errors) > 0 {
		return nil, ErrBlockingPreviewManifest
	}

	payload, err := json.Marshal(struct {
		PreviewToken string `json:"preview_token"`
	}{
		PreviewToken: input.PreviewToken,
	})
	if err != nil {
		return nil, err
	}

	task, err := u.tasks.Create(ctx, importrepo.CreateTaskParams{
		ID:           uuid.New(),
		UserID:       input.UserID,
		Mode:         manifest.Mode,
		ResourceType: "project",
		ResourceID:   manifest.ProjectID,
		Payload:      payload,
	})
	if err != nil {
		return nil, err
	}

	if u.runner != nil {
		if err := u.runner.Run(ctx, task.ID, manifest); err != nil {
			return nil, err
		}
	}
	return task, nil
}
