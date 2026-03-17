package app

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	"github.com/google/uuid"
	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
)

func TestPrepareProjectAnnotationsCreatesPreviewManifest(t *testing.T) {
	t.Parallel()

	projectID := uuid.New()
	datasetID := uuid.New()
	sampleID := uuid.New()
	sessionID := uuid.New()
	ref, err := common.NewSampleRef(common.SampleRefTypeDatasetRelpath, "images/train/sample-1.jpg")
	if err != nil {
		t.Fatalf("NewSampleRef failed: %v", err)
	}

	parser := fakeParser{
		result: &common.ParseProjectAnnotationsResult{
			Batch: buildBatch(),
			SampleRefs: []common.SampleRef{
				ref,
			},
			Samples: []common.ParsedSample{
				{SampleID: "sample-ir-1", Refs: []common.SampleRef{ref}},
			},
			Annotations: []common.ParsedAnnotation{
				{
					AnnotationID:       "ann-ir-1",
					SampleID:           "sample-ir-1",
					PrimarySampleRef:   ref,
					InputGeometryKind:  common.GeometryKindRect,
					OutputGeometryKind: common.GeometryKindRect,
				},
			},
			DetectedGeometryKinds: []common.GeometryKind{common.GeometryKindRect},
			Capabilities: []common.GeometryCapability{
				{InputKind: common.GeometryKindRect, OutputKind: common.GeometryKindRect, Supported: true},
			},
		},
	}

	previewStore := &fakePreviewStore{}
	useCase := NewPrepareProjectAnnotationsUseCase(
		fakeProjectStore{
			project: &projectrepo.Project{ID: projectID, Name: "demo"},
			links: map[string]*projectrepo.ProjectDatasetLink{
				projectDatasetKey(projectID, datasetID): {
					ProjectID: projectID,
					DatasetID: datasetID,
				},
			},
		},
		fakeUploadStore{session: &importrepo.UploadSession{ID: sessionID, Status: "completed", ObjectKey: "/tmp/archive", Mode: "project_annotations"}},
		previewStore,
		fakeMatchStore{
			rows: map[string][]importrepo.SampleMatchRef{
				matchKey(datasetID, "dataset_relpath", "images/train/sample-1.jpg"): {
					{DatasetID: datasetID, SampleID: sampleID, RefType: "dataset_relpath", RefValue: "images/train/sample-1.jpg"},
				},
			},
		},
		fakeParserRegistry{parser: parser},
	)

	result, err := useCase.Execute(context.Background(), PrepareProjectAnnotationsInput{
		ProjectID:       projectID,
		DatasetID:       datasetID,
		UploadSessionID: sessionID,
		FormatProfile:   "coco",
	})
	if err != nil {
		t.Fatalf("Execute failed: %v", err)
	}
	if result.PreviewToken == "" {
		t.Fatal("expected preview token")
	}
	if got, want := result.Summary.TotalAnnotations, 1; got != want {
		t.Fatalf("total annotations got %d want %d", got, want)
	}
	if got, want := result.Summary.MatchedAnnotations, 1; got != want {
		t.Fatalf("matched annotations got %d want %d", got, want)
	}
	if got, want := len(result.LabelPlan.PlannedNewLabels), 1; got != want {
		t.Fatalf("planned labels len got %d want %d", got, want)
	}
	if got, want := result.LabelPlan.PlannedNewLabels[0], "car"; got != want {
		t.Fatalf("planned label got %q want %q", got, want)
	}
	if previewStore.saved == nil {
		t.Fatal("expected preview manifest to be stored")
	}
	if got, want := previewStore.saved.DatasetID, datasetID; got != want {
		t.Fatalf("saved preview dataset_id got %s want %s", got, want)
	}

	var manifest PreviewManifest
	if err := json.Unmarshal(previewStore.saved.Manifest, &manifest); err != nil {
		t.Fatalf("unmarshal manifest: %v", err)
	}
	if got, want := len(manifest.MatchedAnnotations), 1; got != want {
		t.Fatalf("manifest matched annotations len got %d want %d", got, want)
	}
	if got, want := manifest.MatchedAnnotations[0].ResolvedSampleID, sampleID; got != want {
		t.Fatalf("manifest resolved sample id got %s want %s", got, want)
	}
}

func TestPrepareProjectAnnotationsCarriesBlockingErrors(t *testing.T) {
	t.Parallel()

	projectID := uuid.New()
	datasetID := uuid.New()
	sessionID := uuid.New()

	useCase := NewPrepareProjectAnnotationsUseCase(
		fakeProjectStore{
			project: &projectrepo.Project{ID: projectID, Name: "demo"},
			links: map[string]*projectrepo.ProjectDatasetLink{
				projectDatasetKey(projectID, datasetID): {
					ProjectID: projectID,
					DatasetID: datasetID,
				},
			},
		},
		fakeUploadStore{session: &importrepo.UploadSession{ID: sessionID, Status: "completed", ObjectKey: "/tmp/archive", Mode: "project_annotations"}},
		&fakePreviewStore{},
		fakeMatchStore{},
		fakeParserRegistry{
			parser: fakeParser{
				result: &common.ParseProjectAnnotationsResult{
					Batch: &annotationirv1.DataBatchIR{},
					Report: common.ConversionReport{
						Errors: []common.ConversionIssue{{Code: "UNSUPPORTED_GEOMETRY", Message: "polygon unsupported"}},
					},
					UnsupportedGeometryKinds: []common.GeometryKind{common.GeometryKindPolygonSeg},
				},
			},
		},
	)

	result, err := useCase.Execute(context.Background(), PrepareProjectAnnotationsInput{
		ProjectID:       projectID,
		DatasetID:       datasetID,
		UploadSessionID: sessionID,
		FormatProfile:   "coco",
	})
	if err != nil {
		t.Fatalf("Execute failed: %v", err)
	}
	if len(result.Errors) == 0 {
		t.Fatal("expected blocking errors to be carried into prepare result")
	}
	if got, want := len(result.GeometryCapabilities.UnsupportedGeometryKinds), 1; got != want {
		t.Fatalf("unsupported geometry kinds len got %d want %d", got, want)
	}
}

type fakeProjectStore struct {
	project *projectrepo.Project
	links   map[string]*projectrepo.ProjectDatasetLink
}

func (s fakeProjectStore) GetProject(ctx context.Context, id uuid.UUID) (*projectrepo.Project, error) {
	return s.project, nil
}

func (s fakeProjectStore) GetProjectDatasetLink(ctx context.Context, projectID, datasetID uuid.UUID) (*projectrepo.ProjectDatasetLink, error) {
	return s.links[projectDatasetKey(projectID, datasetID)], nil
}

type fakeUploadStore struct {
	session *importrepo.UploadSession
}

func (s fakeUploadStore) Get(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error) {
	return s.session, nil
}

type fakePreviewStore struct {
	saved *importrepo.PreviewManifest
}

func (s *fakePreviewStore) Put(ctx context.Context, params importrepo.PutPreviewManifestParams) (*importrepo.PreviewManifest, error) {
	s.saved = &importrepo.PreviewManifest{
		Token:           params.Token,
		Mode:            params.Mode,
		ProjectID:       params.ProjectID,
		DatasetID:       params.DatasetID,
		UploadSessionID: params.UploadSessionID,
		Manifest:        params.Manifest,
		ParamsHash:      params.ParamsHash,
		ExpiresAt:       params.ExpiresAt,
		CreatedAt:       time.Now(),
	}
	return s.saved, nil
}

func projectDatasetKey(projectID, datasetID uuid.UUID) string {
	return projectID.String() + "|" + datasetID.String()
}

type fakeParserRegistry struct {
	parser fakeParser
}

func (r fakeParserRegistry) ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*common.ParseProjectAnnotationsResult, error) {
	return r.parser.ParseProjectAnnotations(ctx, req)
}

type fakeParser struct {
	result *common.ParseProjectAnnotationsResult
	err    error
}

func (p fakeParser) ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*common.ParseProjectAnnotationsResult, error) {
	return p.result, p.err
}

func buildBatch() *annotationirv1.DataBatchIR {
	return &annotationirv1.DataBatchIR{
		Items: []*annotationirv1.DataItemIR{
			{
				Item: &annotationirv1.DataItemIR_Label{
					Label: &annotationirv1.LabelRecord{Id: "label-ir-1", Name: "car"},
				},
			},
			{
				Item: &annotationirv1.DataItemIR_Sample{
					Sample: &annotationirv1.SampleRecord{Id: "sample-ir-1", Width: 1280, Height: 720},
				},
			},
			{
				Item: &annotationirv1.DataItemIR_Annotation{
					Annotation: &annotationirv1.AnnotationRecord{
						Id:         "ann-ir-1",
						SampleId:   "sample-ir-1",
						LabelId:    "label-ir-1",
						Source:     annotationirv1.AnnotationSource_ANNOTATION_SOURCE_IMPORTED,
						Confidence: 1,
						Geometry: &annotationirv1.Geometry{
							Shape: &annotationirv1.Geometry_Rect{
								Rect: &annotationirv1.RectGeometry{X: 10, Y: 20, Width: 100, Height: 50},
							},
						},
					},
				},
			},
		},
	}
}
