package apihttp

import (
	"context"
	"errors"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
)

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
		result = append(result, *toOpenAPIProject(&projects[i]))
	}
	return result, nil
}

func (h *Handlers) GetProject(ctx context.Context, params openapi.GetProjectParams) (*openapi.Project, error) {
	projectID, err := parseProjectID(params.ProjectID)
	if err != nil {
		return nil, err
	}

	project, err := h.get.Execute(ctx, projectID)
	if err != nil || project == nil {
		return nil, err
	}
	return toOpenAPIProject(project), nil
}

func (h *Handlers) LinkProjectDatasets(ctx context.Context, req *openapi.ProjectDatasetLinkRequest, params openapi.LinkProjectDatasetsParams) (openapi.LinkProjectDatasetsRes, error) {
	projectID, err := parseProjectID(params.ProjectID)
	if err != nil {
		return &openapi.LinkProjectDatasetsBadRequest{Code: "bad_request", Message: err.Error()}, nil
	}
	datasetIDs, err := parseDatasetIDs(req.GetDatasetIds())
	if err != nil {
		return &openapi.LinkProjectDatasetsBadRequest{Code: "bad_request", Message: err.Error()}, nil
	}

	linkedIDs, err := h.linkDatasets.Execute(ctx, projectID, datasetIDs)
	if err != nil {
		if errors.Is(err, projectapp.ErrProjectNotFound) {
			return &openapi.LinkProjectDatasetsNotFound{Code: "not_found", Message: "project not found"}, nil
		}
		if errors.Is(err, projectapp.ErrDatasetNotFound) {
			return &openapi.LinkProjectDatasetsNotFound{Code: "not_found", Message: "dataset not found"}, nil
		}
		return nil, err
	}

	response := make(openapi.LinkProjectDatasetsOKApplicationJSON, 0, len(linkedIDs))
	for _, datasetID := range linkedIDs {
		response = append(response, datasetID.String())
	}
	return &response, nil
}

func (h *Handlers) UnlinkProjectDatasets(ctx context.Context, req *openapi.ProjectDatasetLinkRequest, params openapi.UnlinkProjectDatasetsParams) (openapi.UnlinkProjectDatasetsRes, error) {
	projectID, err := parseProjectID(params.ProjectID)
	if err != nil {
		return &openapi.UnlinkProjectDatasetsBadRequest{Code: "bad_request", Message: err.Error()}, nil
	}
	datasetIDs, err := parseDatasetIDs(req.GetDatasetIds())
	if err != nil {
		return &openapi.UnlinkProjectDatasetsBadRequest{Code: "bad_request", Message: err.Error()}, nil
	}

	count, err := h.unlinkDatasets.Execute(ctx, projectID, datasetIDs)
	if err != nil {
		if errors.Is(err, projectapp.ErrProjectNotFound) {
			return &openapi.UnlinkProjectDatasetsNotFound{Code: "not_found", Message: "project not found"}, nil
		}
		return nil, err
	}

	response := openapi.UnlinkProjectDatasetsOKApplicationJSON(count)
	return &response, nil
}

func (h *Handlers) ListProjectDatasets(ctx context.Context, params openapi.ListProjectDatasetsParams) (openapi.ListProjectDatasetsRes, error) {
	projectID, err := parseProjectID(params.ProjectID)
	if err != nil {
		return &openapi.ListProjectDatasetsBadRequest{Code: "bad_request", Message: err.Error()}, nil
	}

	datasetIDs, err := h.listDatasetIDs.Execute(ctx, projectID)
	if err != nil {
		if errors.Is(err, projectapp.ErrProjectNotFound) {
			return &openapi.ListProjectDatasetsNotFound{Code: "not_found", Message: "project not found"}, nil
		}
		return nil, err
	}

	response := make(openapi.ListProjectDatasetsOKApplicationJSON, 0, len(datasetIDs))
	for _, datasetID := range datasetIDs {
		response = append(response, datasetID.String())
	}
	return &response, nil
}

func (h *Handlers) ListProjectDatasetDetails(ctx context.Context, params openapi.ListProjectDatasetDetailsParams) (openapi.ListProjectDatasetDetailsRes, error) {
	projectID, err := parseProjectID(params.ProjectID)
	if err != nil {
		return &openapi.ListProjectDatasetDetailsBadRequest{Code: "bad_request", Message: err.Error()}, nil
	}

	items, err := h.listDatasetDetails.Execute(ctx, projectID)
	if err != nil {
		if errors.Is(err, projectapp.ErrProjectNotFound) {
			return &openapi.ListProjectDatasetDetailsNotFound{Code: "not_found", Message: "project not found"}, nil
		}
		return nil, err
	}

	response := make(openapi.ListProjectDatasetDetailsOKApplicationJSON, 0, len(items))
	for _, item := range items {
		response = append(response, openapi.Dataset{
			ID:   item.ID.String(),
			Name: item.Name,
			Type: item.Type,
		})
	}
	return &response, nil
}
