package domain

import (
	"encoding/json"
	"errors"
	"strings"

	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
)

var (
	ErrInvalidAnnotation = errors.New("invalid annotation")
	ErrSampleNotFound    = errors.New("sample not found")
)

type Annotation struct {
	ID             string
	ProjectID      string
	SampleID       string
	GroupID        string
	LabelID        string
	View           string
	AnnotationType string
	Geometry       map[string]any
	Attrs          map[string]any
	Source         string
	IsGenerated    bool
}

type CreateInput struct {
	GroupID        string
	LabelID        string
	View           string
	AnnotationType string
	Geometry       map[string]any
	Attrs          map[string]any
	Source         string
}

type NormalizedCreateInput struct {
	GroupID        string
	LabelID        string
	View           string
	AnnotationType string
	Geometry       []byte
	Attrs          []byte
	Source         string
}

func NormalizeCreateInput(input CreateInput) (NormalizedCreateInput, error) {
	groupID := strings.TrimSpace(input.GroupID)
	labelID := strings.TrimSpace(input.LabelID)
	view := strings.TrimSpace(input.View)
	annotationType := strings.ToLower(strings.TrimSpace(input.AnnotationType))
	source := strings.TrimSpace(input.Source)
	if source == "" {
		source = "manual"
	}

	if groupID == "" || labelID == "" || view == "" {
		return NormalizedCreateInput{}, ErrInvalidAnnotation
	}
	if annotationType != "rect" && annotationType != "obb" {
		return NormalizedCreateInput{}, ErrInvalidAnnotation
	}

	geometry, err := marshalObject(input.Geometry)
	if err != nil || len(geometry) == 0 || string(geometry) == "null" {
		return NormalizedCreateInput{}, ErrInvalidAnnotation
	}

	attrs, err := marshalOptionalObject(input.Attrs)
	if err != nil {
		return NormalizedCreateInput{}, ErrInvalidAnnotation
	}

	return NormalizedCreateInput{
		GroupID:        groupID,
		LabelID:        labelID,
		View:           view,
		AnnotationType: annotationType,
		Geometry:       geometry,
		Attrs:          attrs,
		Source:         source,
	}, nil
}

func FromRepoAnnotation(annotation annotationrepo.Annotation) (Annotation, error) {
	geometry, err := decodeObject(annotation.Geometry)
	if err != nil {
		return Annotation{}, err
	}
	attrs, err := decodeObject(annotation.Attrs)
	if err != nil {
		return Annotation{}, err
	}

	return Annotation{
		ID:             annotation.ID.String(),
		ProjectID:      annotation.ProjectID.String(),
		SampleID:       annotation.SampleID.String(),
		GroupID:        annotation.GroupID,
		LabelID:        annotation.LabelID,
		View:           annotation.View,
		AnnotationType: annotation.AnnotationType,
		Geometry:       geometry,
		Attrs:          attrs,
		Source:         annotation.Source,
		IsGenerated:    annotation.IsGenerated,
	}, nil
}

func marshalObject(value map[string]any) ([]byte, error) {
	return json.Marshal(value)
}

func marshalOptionalObject(value map[string]any) ([]byte, error) {
	if value == nil {
		return []byte(`{}`), nil
	}
	return json.Marshal(value)
}

func decodeObject(raw []byte) (map[string]any, error) {
	if len(raw) == 0 {
		return map[string]any{}, nil
	}

	var value map[string]any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	if value == nil {
		return map[string]any{}, nil
	}
	return value, nil
}
