package app

import (
	"context"

	"github.com/google/uuid"

	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
)

type ListAnnotationsUseCase struct {
	samples     SampleStore
	projects    ProjectDatasetStore
	annotations AnnotationStore
}

func NewListAnnotationsUseCase(samples SampleStore, projects ProjectDatasetStore, annotations AnnotationStore) *ListAnnotationsUseCase {
	return &ListAnnotationsUseCase{
		samples:     samples,
		projects:    projects,
		annotations: annotations,
	}
}

func (u *ListAnnotationsUseCase) Execute(ctx context.Context, projectID, sampleID uuid.UUID) ([]annotationdomain.Annotation, error) {
	sample, err := u.samples.Get(ctx, sampleID)
	if err != nil {
		return nil, err
	}
	if sample == nil {
		return nil, annotationdomain.ErrSampleNotFound
	}
	if u.projects != nil {
		link, err := u.projects.GetProjectDatasetLink(ctx, projectID, sample.DatasetID)
		if err != nil {
			return nil, err
		}
		if link == nil {
			return nil, annotationdomain.ErrSampleNotFound
		}
	}

	rows, err := u.annotations.ListByProjectSample(ctx, projectID, sampleID)
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
