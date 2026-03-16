package app

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	annotationmapping "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app/mapping"
	annotationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/domain"
	annotationrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/repo"
)

func TestCreateAnnotationWithFedoMappingCreatesSourceAndGeneratedAnnotations(t *testing.T) {
	sampleID := uuid.New()
	store := &fakeAnnotationStore{
		nextIDs: []uuid.UUID{uuid.New(), uuid.New()},
	}
	useCase := NewCreateAnnotationUseCase(
		&fakeSampleStore{
			sample: &annotationrepo.Sample{
				ID:          sampleID,
				DatasetType: "fedo-dual-view",
				Meta:        []byte(`{"mapping":{"source_view":"rgb","target_view":"thermal","lookup_table_b64":"bG9va3VwLWJ5dGVz","time_gap_threshold":8}}`),
			},
		},
		store,
		&fakeMapper{
			response: annotationmapping.MapFedoOBBResponse{
				MappedGeometries: []map[string]any{
					{
						"obb": map[string]any{
							"cx":     30,
							"cy":     40,
							"width":  5,
							"height": 6,
							"angle":  12,
						},
					},
				},
			},
		},
	)

	annotations, err := useCase.Execute(context.Background(), sampleID, annotationdomain.CreateInput{
		GroupID:        "group-a",
		LabelID:        "car",
		View:           "rgb",
		AnnotationType: "obb",
		Geometry: map[string]any{
			"cx":     10,
			"cy":     20,
			"width":  4,
			"height": 5,
			"angle":  6,
		},
		Source: "manual",
	})
	if err != nil {
		t.Fatalf("execute create annotation: %v", err)
	}

	if len(store.created) != 2 || len(annotations) != 2 {
		t.Fatalf("expected source and generated annotations, got created=%d annotations=%d", len(store.created), len(annotations))
	}
	if store.created[0].View != "rgb" || store.created[0].IsGenerated {
		t.Fatalf("unexpected source annotation params: %+v", store.created[0])
	}
	if store.created[1].View != "thermal" || !store.created[1].IsGenerated {
		t.Fatalf("unexpected generated annotation params: %+v", store.created[1])
	}
	if store.created[1].Source != "system" {
		t.Fatalf("unexpected generated source: %+v", store.created[1])
	}
}

func TestCreateAnnotationFailsBeforeWriteWhenMappingFails(t *testing.T) {
	sampleID := uuid.New()
	store := &fakeAnnotationStore{
		nextIDs: []uuid.UUID{uuid.New()},
	}
	useCase := NewCreateAnnotationUseCase(
		&fakeSampleStore{
			sample: &annotationrepo.Sample{
				ID:          sampleID,
				DatasetType: "fedo-dual-view",
				Meta:        []byte(`{"mapping":{"source_view":"rgb","target_view":"thermal","lookup_table_b64":"bG9va3VwLWJ5dGVz"}}`),
			},
		},
		store,
		&fakeMapper{err: errors.New("mapping failed")},
	)

	_, err := useCase.Execute(context.Background(), sampleID, annotationdomain.CreateInput{
		GroupID:        "group-a",
		LabelID:        "car",
		View:           "rgb",
		AnnotationType: "obb",
		Geometry: map[string]any{
			"cx":     10,
			"cy":     20,
			"width":  4,
			"height": 5,
			"angle":  6,
		},
		Source: "manual",
	})
	if err == nil {
		t.Fatal("expected mapping error")
	}
	if len(store.created) != 0 {
		t.Fatalf("expected no writes on mapping error, got %+v", store.created)
	}
}

type fakeSampleStore struct {
	sample *annotationrepo.Sample
}

func (f *fakeSampleStore) Get(context.Context, uuid.UUID) (*annotationrepo.Sample, error) {
	return f.sample, nil
}

type fakeAnnotationStore struct {
	nextIDs []uuid.UUID
	created []annotationrepo.CreateAnnotationParams
}

func (f *fakeAnnotationStore) Create(_ context.Context, params annotationrepo.CreateAnnotationParams) (*annotationrepo.Annotation, error) {
	f.created = append(f.created, params)
	id := uuid.New()
	if len(f.nextIDs) > 0 {
		id = f.nextIDs[0]
		f.nextIDs = f.nextIDs[1:]
	}
	return &annotationrepo.Annotation{
		ID:             id,
		SampleID:       params.SampleID,
		GroupID:        params.GroupID,
		LabelID:        params.LabelID,
		View:           params.View,
		AnnotationType: params.AnnotationType,
		Geometry:       params.Geometry,
		Attrs:          params.Attrs,
		Source:         params.Source,
		IsGenerated:    params.IsGenerated,
	}, nil
}

func (f *fakeAnnotationStore) ListBySample(context.Context, uuid.UUID) ([]annotationrepo.Annotation, error) {
	return nil, nil
}

type fakeMapper struct {
	response annotationmapping.MapFedoOBBResponse
	err      error
}

func (f *fakeMapper) MapFedoOBB(context.Context, annotationmapping.MapFedoOBBRequest) (annotationmapping.MapFedoOBBResponse, error) {
	if f.err != nil {
		return annotationmapping.MapFedoOBBResponse{}, f.err
	}
	return f.response, nil
}
