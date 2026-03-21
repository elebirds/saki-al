package apihttp

import (
	"encoding/json"

	"github.com/go-faster/jx"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
)

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
