package apihttp

import (
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
)

func toOpenAPIProject(project *projectapp.Project) *openapi.Project {
	return &openapi.Project{
		ID:   project.ID.String(),
		Name: project.Name,
	}
}
