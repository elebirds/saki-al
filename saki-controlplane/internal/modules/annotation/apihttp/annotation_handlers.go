package apihttp

import (
	"context"

	"github.com/google/uuid"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
)

func (h *Handlers) CreateSampleAnnotations(ctx context.Context, req *openapi.CreateAnnotationRequest, params openapi.CreateSampleAnnotationsParams) ([]openapi.Annotation, error) {
	projectID, err := uuid.Parse(params.ProjectID)
	if err != nil {
		return nil, err
	}
	sampleID, err := uuid.Parse(params.SampleID)
	if err != nil {
		return nil, err
	}

	geometry, err := decodeRawMap(req.GetGeometry())
	if err != nil {
		return nil, err
	}

	attrs := map[string]any{}
	if rawAttrs, ok := req.GetAttrs().Get(); ok {
		attrs, err = decodeRawMap(rawAttrs)
		if err != nil {
			return nil, err
		}
	}

	annotations, err := h.create.Execute(ctx, projectID, sampleID, annotationdomain.CreateInput{
		GroupID:        req.GetGroupID(),
		LabelID:        req.GetLabelID(),
		View:           req.GetView(),
		AnnotationType: req.GetAnnotationType(),
		Geometry:       geometry,
		Attrs:          attrs,
		Source:         req.GetSource().Or("manual"),
	})
	if err != nil {
		return nil, err
	}

	return toOpenAPIAnnotations(annotations)
}

func (h *Handlers) ListSampleAnnotations(ctx context.Context, params openapi.ListSampleAnnotationsParams) ([]openapi.Annotation, error) {
	projectID, err := uuid.Parse(params.ProjectID)
	if err != nil {
		return nil, err
	}
	sampleID, err := uuid.Parse(params.SampleID)
	if err != nil {
		return nil, err
	}

	annotations, err := h.list.Execute(ctx, projectID, sampleID)
	if err != nil {
		return nil, err
	}
	return toOpenAPIAnnotations(annotations)
}
