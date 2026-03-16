package app

import (
	"context"

	"github.com/google/uuid"

	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
)

type ListAnnotationsUseCase struct {
	annotations AnnotationStore
}

func NewListAnnotationsUseCase(annotations AnnotationStore) *ListAnnotationsUseCase {
	return &ListAnnotationsUseCase{annotations: annotations}
}

func (u *ListAnnotationsUseCase) Execute(ctx context.Context, sampleID uuid.UUID) ([]annotationdomain.Annotation, error) {
	rows, err := u.annotations.ListBySample(ctx, sampleID)
	if err != nil {
		return nil, err
	}

	result := make([]annotationdomain.Annotation, 0, len(rows))
	for _, row := range rows {
		annotation, err := annotationdomain.FromRepoAnnotation(row)
		if err != nil {
			return nil, err
		}
		result = append(result, annotation)
	}

	return result, nil
}
