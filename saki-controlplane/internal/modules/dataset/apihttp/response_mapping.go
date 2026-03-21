package apihttp

import (
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
)

func toOpenAPIDataset(dataset *datasetapp.Dataset) *openapi.Dataset {
	if dataset == nil {
		return nil
	}
	return &openapi.Dataset{
		ID:   dataset.ID.String(),
		Name: dataset.Name,
		Type: dataset.Type,
	}
}
