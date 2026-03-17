package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
)

type Annotation struct {
	ID             uuid.UUID
	ProjectID      uuid.UUID
	SampleID       uuid.UUID
	GroupID        string
	LabelID        string
	View           string
	AnnotationType string
	Geometry       []byte
	Attrs          []byte
	Source         string
	IsGenerated    bool
	CreatedAt      time.Time
}

type CreateAnnotationParams struct {
	ProjectID      uuid.UUID
	SampleID       uuid.UUID
	GroupID        string
	LabelID        string
	View           string
	AnnotationType string
	Geometry       []byte
	Attrs          []byte
	Source         string
	IsGenerated    bool
}

type AnnotationRepo struct {
	q *sqlcdb.Queries
}

func NewAnnotationRepo(pool *pgxpool.Pool) *AnnotationRepo {
	return &AnnotationRepo{q: sqlcdb.New(pool)}
}

func (r *AnnotationRepo) Create(ctx context.Context, params CreateAnnotationParams) (*Annotation, error) {
	row, err := r.q.CreateAnnotation(ctx, sqlcdb.CreateAnnotationParams{
		ProjectID:      params.ProjectID,
		SampleID:       params.SampleID,
		GroupID:        params.GroupID,
		LabelID:        params.LabelID,
		View:           params.View,
		AnnotationType: params.AnnotationType,
		Geometry:       params.Geometry,
		Attrs:          params.Attrs,
		Source:         params.Source,
		IsGenerated:    params.IsGenerated,
	})
	if err != nil {
		return nil, err
	}

	return &Annotation{
		ID:             row.ID,
		ProjectID:      row.ProjectID,
		SampleID:       row.SampleID,
		GroupID:        row.GroupID,
		LabelID:        row.LabelID,
		View:           row.View,
		AnnotationType: row.AnnotationType,
		Geometry:       row.Geometry,
		Attrs:          row.Attrs,
		Source:         row.Source,
		IsGenerated:    row.IsGenerated,
		CreatedAt:      row.CreatedAt.Time,
	}, nil
}

func (r *AnnotationRepo) ListByProjectSample(ctx context.Context, projectID, sampleID uuid.UUID) ([]Annotation, error) {
	rows, err := r.q.ListAnnotationsByProjectSample(ctx, sqlcdb.ListAnnotationsByProjectSampleParams{
		ProjectID: projectID,
		SampleID:  sampleID,
	})
	if err != nil {
		return nil, err
	}

	annotations := make([]Annotation, 0, len(rows))
	for _, row := range rows {
		annotations = append(annotations, Annotation{
			ID:             row.ID,
			ProjectID:      row.ProjectID,
			SampleID:       row.SampleID,
			GroupID:        row.GroupID,
			LabelID:        row.LabelID,
			View:           row.View,
			AnnotationType: row.AnnotationType,
			Geometry:       row.Geometry,
			Attrs:          row.Attrs,
			Source:         row.Source,
			IsGenerated:    row.IsGenerated,
			CreatedAt:      row.CreatedAt.Time,
		})
	}

	return annotations, nil
}
