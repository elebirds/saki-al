package apihttp

import (
	"context"
	"errors"
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	"github.com/google/uuid"
)

type Handlers struct {
	create *datasetapp.CreateDatasetUseCase
	list   *datasetapp.ListDatasetsUseCase
	get    *datasetapp.GetDatasetUseCase
	update *datasetapp.UpdateDatasetUseCase
	delete *datasetapp.DeleteDatasetUseCase
}

func NewHandlers(store datasetapp.Store) *Handlers {
	return &Handlers{
		create: datasetapp.NewCreateDatasetUseCase(store),
		list:   datasetapp.NewListDatasetsUseCase(store),
		get:    datasetapp.NewGetDatasetUseCase(store),
		update: datasetapp.NewUpdateDatasetUseCase(store),
		delete: datasetapp.NewDeleteDatasetUseCase(store),
	}
}

func (h *Handlers) CreateDataset(ctx context.Context, req *openapi.CreateDatasetRequest) (*openapi.Dataset, error) {
	dataset, err := h.create.Execute(ctx, datasetapp.CreateDatasetInput{
		Name: req.GetName(),
		Type: req.GetType(),
	})
	if err != nil {
		if errors.Is(err, datasetapp.ErrInvalidDatasetInput) {
			return nil, badRequestError("invalid dataset input")
		}
		return nil, err
	}
	return toOpenAPIDataset(dataset), nil
}

func (h *Handlers) ListDatasets(ctx context.Context, params openapi.ListDatasetsParams) (*openapi.DatasetListResponse, error) {
	page, _ := params.Page.Get()
	limit, _ := params.Limit.Get()
	query, _ := params.Q.Get()

	result, err := h.list.Execute(ctx, datasetapp.ListDatasetsInput{
		Page:  int(page),
		Limit: int(limit),
		Query: query,
	})
	if err != nil {
		return nil, err
	}

	items := make([]openapi.Dataset, 0, len(result.Items))
	for i := range result.Items {
		items = append(items, *toOpenAPIDataset(&result.Items[i]))
	}

	return &openapi.DatasetListResponse{
		Items:   items,
		Total:   int32(result.Total),
		Offset:  int32(result.Offset),
		Limit:   int32(result.Limit),
		Size:    int32(result.Size),
		HasMore: result.HasMore,
	}, nil
}

func (h *Handlers) GetDataset(ctx context.Context, params openapi.GetDatasetParams) (openapi.GetDatasetRes, error) {
	datasetID, err := parseDatasetID(params.DatasetID)
	if err != nil {
		return &openapi.GetDatasetBadRequest{
			Code:    "bad_request",
			Message: err.Error(),
		}, nil
	}

	dataset, err := h.get.Execute(ctx, datasetID)
	if err != nil {
		return nil, err
	}
	if dataset == nil {
		return &openapi.GetDatasetNotFound{
			Code:    "not_found",
			Message: "dataset not found",
		}, nil
	}

	return toOpenAPIDataset(dataset), nil
}

func (h *Handlers) UpdateDataset(ctx context.Context, req *openapi.UpdateDatasetRequest, params openapi.UpdateDatasetParams) (openapi.UpdateDatasetRes, error) {
	datasetID, err := parseDatasetID(params.DatasetID)
	if err != nil {
		return &openapi.UpdateDatasetBadRequest{
			Code:    "bad_request",
			Message: err.Error(),
		}, nil
	}

	updated, err := h.update.Execute(ctx, datasetapp.UpdateDatasetInput{
		ID:   datasetID,
		Name: req.GetName(),
		Type: req.GetType(),
	})
	if err != nil {
		if errors.Is(err, datasetapp.ErrInvalidDatasetInput) {
			return &openapi.UpdateDatasetBadRequest{
				Code:    "bad_request",
				Message: "invalid dataset input",
			}, nil
		}
		return nil, err
	}
	if updated == nil {
		return &openapi.UpdateDatasetNotFound{
			Code:    "not_found",
			Message: "dataset not found",
		}, nil
	}

	return toOpenAPIDataset(updated), nil
}

func (h *Handlers) DeleteDataset(ctx context.Context, params openapi.DeleteDatasetParams) (openapi.DeleteDatasetRes, error) {
	datasetID, err := parseDatasetID(params.DatasetID)
	if err != nil {
		return &openapi.DeleteDatasetBadRequest{
			Code:    "bad_request",
			Message: err.Error(),
		}, nil
	}

	deleted, err := h.delete.Execute(ctx, datasetID)
	if err != nil {
		return nil, err
	}
	if !deleted {
		return &openapi.DeleteDatasetNotFound{
			Code:    "not_found",
			Message: "dataset not found",
		}, nil
	}
	return &openapi.DeleteDatasetNoContent{}, nil
}

func parseDatasetID(raw string) (uuid.UUID, error) {
	datasetID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid dataset_id")
	}
	return datasetID, nil
}

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

func badRequestError(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusBadRequest,
		Response: openapi.ErrorResponse{
			Code:    "bad_request",
			Message: message,
		},
	}
}
