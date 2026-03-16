package app

import (
	"context"

	"github.com/google/uuid"

	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
)

type SampleStore interface {
	Get(ctx context.Context, sampleID uuid.UUID) (*annotationrepo.Sample, error)
}

type AnnotationStore interface {
	Create(ctx context.Context, params annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error)
	ListBySample(ctx context.Context, sampleID uuid.UUID) ([]annotationrepo.Annotation, error)
}

type CreateAnnotationUseCase struct {
	samples     SampleStore
	annotations AnnotationStore
}

func NewCreateAnnotationUseCase(samples SampleStore, annotations AnnotationStore) *CreateAnnotationUseCase {
	return &CreateAnnotationUseCase{
		samples:     samples,
		annotations: annotations,
	}
}

func (u *CreateAnnotationUseCase) Execute(ctx context.Context, sampleID uuid.UUID, input annotationdomain.CreateInput) ([]annotationdomain.Annotation, error) {
	sample, err := u.samples.Get(ctx, sampleID)
	if err != nil {
		return nil, err
	}
	if sample == nil {
		return nil, annotationdomain.ErrSampleNotFound
	}

	normalized, err := annotationdomain.NormalizeCreateInput(input)
	if err != nil {
		return nil, err
	}

	created, err := u.annotations.Create(ctx, annotationrepo.CreateAnnotationParams{
		SampleID:       sample.ID,
		GroupID:        normalized.GroupID,
		LabelID:        normalized.LabelID,
		View:           normalized.View,
		AnnotationType: normalized.AnnotationType,
		Geometry:       normalized.Geometry,
		Attrs:          normalized.Attrs,
		Source:         normalized.Source,
		IsGenerated:    false,
	})
	if err != nil {
		return nil, err
	}

	annotation, err := annotationdomain.FromRepoAnnotation(*created)
	if err != nil {
		return nil, err
	}

	return []annotationdomain.Annotation{annotation}, nil
}
