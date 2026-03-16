package apihttp

import (
	"context"
	"encoding/json"

	"github.com/go-faster/jx"
	"github.com/google/uuid"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	annotationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app"
	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
)

type Handlers struct {
	create *annotationapp.CreateAnnotationUseCase
	list   *annotationapp.ListAnnotationsUseCase
}

func NewHandlers(samples annotationapp.SampleStore, annotations annotationapp.AnnotationStore) *Handlers {
	return &Handlers{
		create: annotationapp.NewCreateAnnotationUseCase(samples, annotations),
		list:   annotationapp.NewListAnnotationsUseCase(annotations),
	}
}

func (h *Handlers) CreateSampleAnnotations(ctx context.Context, req *openapi.CreateAnnotationRequest, params openapi.CreateSampleAnnotationsParams) ([]openapi.Annotation, error) {
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

	annotations, err := h.create.Execute(ctx, sampleID, annotationdomain.CreateInput{
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
	sampleID, err := uuid.Parse(params.SampleID)
	if err != nil {
		return nil, err
	}

	annotations, err := h.list.Execute(ctx, sampleID)
	if err != nil {
		return nil, err
	}

	return toOpenAPIAnnotations(annotations)
}

func toOpenAPIAnnotations(annotations []annotationdomain.Annotation) ([]openapi.Annotation, error) {
	result := make([]openapi.Annotation, 0, len(annotations))
	for _, annotation := range annotations {
		geometry, err := encodeRawMap(annotation.Geometry)
		if err != nil {
			return nil, err
		}
		attrs, err := encodeRawMap(annotation.Attrs)
		if err != nil {
			return nil, err
		}

		result = append(result, openapi.Annotation{
			ID:             annotation.ID,
			SampleID:       annotation.SampleID,
			GroupID:        annotation.GroupID,
			LabelID:        annotation.LabelID,
			View:           annotation.View,
			AnnotationType: annotation.AnnotationType,
			Geometry:       openapi.AnnotationGeometry(geometry),
			Attrs:          openapi.AnnotationAttrs(attrs),
			Source:         annotation.Source,
			IsGenerated:    annotation.IsGenerated,
		})
	}
	return result, nil
}

func decodeRawMap[T ~map[string]jx.Raw](raw T) (map[string]any, error) {
	result := make(map[string]any, len(raw))
	for key, value := range raw {
		var decoded any
		if err := json.Unmarshal(value, &decoded); err != nil {
			return nil, err
		}
		result[key] = decoded
	}
	return result, nil
}

func encodeRawMap(value map[string]any) (map[string]jx.Raw, error) {
	result := make(map[string]jx.Raw, len(value))
	for key, item := range value {
		raw, err := json.Marshal(item)
		if err != nil {
			return nil, err
		}
		result[key] = jx.Raw(raw)
	}
	return result, nil
}
