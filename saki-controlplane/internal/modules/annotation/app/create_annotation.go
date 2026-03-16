package app

import (
	"context"
	"encoding/base64"
	"encoding/json"

	"github.com/google/uuid"

	annotationmapping "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app/mapping"
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

type Mapper interface {
	MapFedoOBB(ctx context.Context, req annotationmapping.MapFedoOBBRequest) (annotationmapping.MapFedoOBBResponse, error)
}

type CreateAnnotationUseCase struct {
	samples     SampleStore
	annotations AnnotationStore
	mapper      Mapper
}

func NewCreateAnnotationUseCase(samples SampleStore, annotations AnnotationStore, mapper Mapper) *CreateAnnotationUseCase {
	return &CreateAnnotationUseCase{
		samples:     samples,
		annotations: annotations,
		mapper:      mapper,
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

	createParams := []annotationrepo.CreateAnnotationParams{{
		SampleID:       sample.ID,
		GroupID:        normalized.GroupID,
		LabelID:        normalized.LabelID,
		View:           normalized.View,
		AnnotationType: normalized.AnnotationType,
		Geometry:       normalized.Geometry,
		Attrs:          normalized.Attrs,
		Source:         normalized.Source,
		IsGenerated:    false,
	}}

	mappedParams, err := u.buildMappedAnnotations(ctx, sample, normalized, input.Geometry)
	if err != nil {
		return nil, err
	}
	createParams = append(createParams, mappedParams...)

	result := make([]annotationdomain.Annotation, 0, len(createParams))
	for _, params := range createParams {
		created, err := u.annotations.Create(ctx, params)
		if err != nil {
			return nil, err
		}

		annotation, err := annotationdomain.FromRepoAnnotation(*created)
		if err != nil {
			return nil, err
		}
		result = append(result, annotation)
	}

	return result, nil
}

type fedoMappingMeta struct {
	Mapping *struct {
		SourceView       string `json:"source_view"`
		TargetView       string `json:"target_view"`
		LookupTableB64   string `json:"lookup_table_b64"`
		TimeGapThreshold int    `json:"time_gap_threshold"`
	} `json:"mapping"`
	SourceView       string `json:"source_view"`
	TargetView       string `json:"target_view"`
	LookupTableB64   string `json:"lookup_table_b64"`
	TimeGapThreshold int    `json:"time_gap_threshold"`
}

func (u *CreateAnnotationUseCase) buildMappedAnnotations(ctx context.Context, sample *annotationrepo.Sample, normalized annotationdomain.NormalizedCreateInput, sourceGeometry map[string]any) ([]annotationrepo.CreateAnnotationParams, error) {
	if u.mapper == nil || sample == nil {
		return nil, nil
	}
	if sample.DatasetType != "fedo-dual-view" || normalized.AnnotationType != "obb" {
		return nil, nil
	}

	cfg, ok, err := decodeFedoMappingMeta(sample.Meta)
	if err != nil || !ok {
		return nil, err
	}
	if normalized.View != cfg.SourceView {
		return nil, nil
	}

	response, err := u.mapper.MapFedoOBB(ctx, annotationmapping.MapFedoOBBRequest{
		SourceView:       cfg.SourceView,
		TargetView:       cfg.TargetView,
		SourceGeometry:   sourceGeometry,
		LookupTable:      cfg.LookupTable,
		TimeGapThreshold: cfg.TimeGapThreshold,
	})
	if err != nil {
		return nil, err
	}

	params := make([]annotationrepo.CreateAnnotationParams, 0, len(response.MappedGeometries))
	for _, geometry := range response.MappedGeometries {
		rawGeometry, err := json.Marshal(geometry)
		if err != nil {
			return nil, err
		}
		params = append(params, annotationrepo.CreateAnnotationParams{
			SampleID:       sample.ID,
			GroupID:        normalized.GroupID,
			LabelID:        normalized.LabelID,
			View:           cfg.TargetView,
			AnnotationType: normalized.AnnotationType,
			Geometry:       rawGeometry,
			Attrs:          normalized.Attrs,
			Source:         "system",
			IsGenerated:    true,
		})
	}
	return params, nil
}

type fedoMappingConfig struct {
	SourceView       string
	TargetView       string
	LookupTable      []byte
	TimeGapThreshold int
}

func decodeFedoMappingMeta(raw []byte) (fedoMappingConfig, bool, error) {
	if len(raw) == 0 {
		return fedoMappingConfig{}, false, nil
	}

	var meta fedoMappingMeta
	if err := json.Unmarshal(raw, &meta); err != nil {
		return fedoMappingConfig{}, false, err
	}

	sourceView := meta.SourceView
	targetView := meta.TargetView
	lookupTableB64 := meta.LookupTableB64
	timeGapThreshold := meta.TimeGapThreshold
	if meta.Mapping != nil {
		sourceView = meta.Mapping.SourceView
		targetView = meta.Mapping.TargetView
		lookupTableB64 = meta.Mapping.LookupTableB64
		timeGapThreshold = meta.Mapping.TimeGapThreshold
	}
	if sourceView == "" || targetView == "" || lookupTableB64 == "" {
		return fedoMappingConfig{}, false, nil
	}

	lookupTable, err := base64.StdEncoding.DecodeString(lookupTableB64)
	if err != nil {
		return fedoMappingConfig{}, false, err
	}

	return fedoMappingConfig{
		SourceView:       sourceView,
		TargetView:       targetView,
		LookupTable:      lookupTable,
		TimeGapThreshold: timeGapThreshold,
	}, true, nil
}
