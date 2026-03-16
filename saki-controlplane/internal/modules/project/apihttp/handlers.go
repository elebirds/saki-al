package apihttp

import (
	"context"

	"github.com/google/uuid"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
)

type Handlers struct {
	create *projectapp.CreateProjectUseCase
	list   *projectapp.ListProjectsUseCase
	get    *projectapp.GetProjectUseCase
}

func NewHandlers(store projectapp.Store) *Handlers {
	return &Handlers{
		create: projectapp.NewCreateProjectUseCase(store),
		list:   projectapp.NewListProjectsUseCase(store),
		get:    projectapp.NewGetProjectUseCase(store),
	}
}

func (h *Handlers) CreateProject(ctx context.Context, req *openapi.CreateProjectRequest) (*openapi.Project, error) {
	project, err := h.create.Execute(ctx, req.GetName())
	if err != nil {
		return nil, err
	}
	return toOpenAPIProject(project), nil
}

func (h *Handlers) ListProjects(ctx context.Context) ([]openapi.Project, error) {
	projects, err := h.list.Execute(ctx)
	if err != nil {
		return nil, err
	}

	result := make([]openapi.Project, 0, len(projects))
	for i := range projects {
		project := projects[i]
		result = append(result, openapi.Project{
			ID:   project.ID.String(),
			Name: project.Name,
		})
	}

	return result, nil
}

func (h *Handlers) GetProject(ctx context.Context, params openapi.GetProjectParams) (*openapi.Project, error) {
	projectID, err := uuid.Parse(params.ProjectID)
	if err != nil {
		return nil, err
	}

	project, err := h.get.Execute(ctx, projectID)
	if err != nil || project == nil {
		return nil, err
	}

	return toOpenAPIProject(project), nil
}

func toOpenAPIProject(project *projectapp.Project) *openapi.Project {
	return &openapi.Project{
		ID:   project.ID.String(),
		Name: project.Name,
	}
}
