package app

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
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

	parser := &fakeParser{
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
	objectKey := "imports/" + sessionID.String() + "/annotations.zip"
	provider := &fakePrepareObjectProvider{
		downloadBodies: map[string][]byte{
			objectKey: buildPrepareZipArchive(t, "annotations.json", `{"images":[],"categories":[],"annotations":[]}`),
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
		fakeUploadStore{session: &importrepo.UploadSession{ID: sessionID, Status: "completed", ObjectKey: objectKey, Mode: "project_annotations"}},
		previewStore,
		fakeMatchStore{
			rows: map[string][]importrepo.SampleMatchRef{
				matchKey(datasetID, "dataset_relpath", "images/train/sample-1.jpg"): {
					{DatasetID: datasetID, SampleID: sampleID, RefType: "dataset_relpath", RefValue: "images/train/sample-1.jpg"},
				},
			},
		},
		fakeParserRegistry{parser: parser},
		provider,
	)

	input := PrepareProjectAnnotationsInput{
		ProjectID:       projectID,
		DatasetID:       datasetID,
		UploadSessionID: sessionID,
		FormatProfile:   "coco",
	}
	result, err := useCase.Execute(context.Background(), input)
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
	if got, want := provider.lastDownloadObjectKey, objectKey; got != want {
		t.Fatalf("download object key got %q want %q", got, want)
	}
	if parser.lastReq.SourcePath == "" || parser.lastReq.SourcePath == objectKey {
		t.Fatalf("expected parser source path resolved from downloaded file, got %q", parser.lastReq.SourcePath)
	}
	if !strings.HasSuffix(strings.ToLower(parser.lastReq.SourcePath), ".json") {
		t.Fatalf("expected parser source path to point to extracted coco json, got %q", parser.lastReq.SourcePath)
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
	if got, want := manifest.SourcePath, objectKey; got != want {
		t.Fatalf("manifest source path got %q want %q", got, want)
	}
	if got, want := previewStore.saved.ParamsHash, paramsHash(input, objectKey); got != want {
		t.Fatalf("params hash got %q want %q", got, want)
	}
}

func TestPrepareProjectAnnotationsCarriesBlockingErrors(t *testing.T) {
	t.Parallel()

	projectID := uuid.New()
	datasetID := uuid.New()
	sessionID := uuid.New()

	objectKey := "imports/" + sessionID.String() + "/annotations.zip"
	provider := &fakePrepareObjectProvider{
		downloadBodies: map[string][]byte{
			objectKey: buildPrepareZipArchive(t, "annotations.json", `{"images":[],"categories":[],"annotations":[]}`),
		},
	}

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
		fakeUploadStore{session: &importrepo.UploadSession{ID: sessionID, Status: "completed", ObjectKey: objectKey, Mode: "project_annotations"}},
		&fakePreviewStore{},
		fakeMatchStore{},
		fakeParserRegistry{
			parser: &fakeParser{
				result: &common.ParseProjectAnnotationsResult{
					Batch: &annotationirv1.DataBatchIR{},
					Report: common.ConversionReport{
						Errors: []common.ConversionIssue{{Code: "UNSUPPORTED_GEOMETRY", Message: "polygon unsupported"}},
					},
					UnsupportedGeometryKinds: []common.GeometryKind{common.GeometryKindPolygonSeg},
				},
			},
		},
		provider,
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
	parser *fakeParser
}

func (r fakeParserRegistry) ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*common.ParseProjectAnnotationsResult, error) {
	if r.parser == nil {
		return nil, errors.New("parser is nil")
	}
	return r.parser.ParseProjectAnnotations(ctx, req)
}

type fakeParser struct {
	result  *common.ParseProjectAnnotationsResult
	err     error
	lastReq ParseProjectAnnotationsRequest
}

func (p *fakeParser) ParseProjectAnnotations(ctx context.Context, req ParseProjectAnnotationsRequest) (*common.ParseProjectAnnotationsResult, error) {
	p.lastReq = req
	return p.result, p.err
}

type fakePrepareObjectProvider struct {
	downloadBodies map[string][]byte

	lastDownloadObjectKey string
	lastDownloadDst       string
}

func (p *fakePrepareObjectProvider) Bucket() string { return "imports" }

func (p *fakePrepareObjectProvider) SignPutObject(context.Context, string, time.Duration, string) (string, error) {
	return "", nil
}

func (p *fakePrepareObjectProvider) SignGetObject(context.Context, string, time.Duration) (string, error) {
	return "", nil
}

func (p *fakePrepareObjectProvider) StatObject(context.Context, string) (*storage.ObjectStat, error) {
	return nil, nil
}

func (p *fakePrepareObjectProvider) DownloadObject(_ context.Context, objectKey string, dst string) error {
	p.lastDownloadObjectKey = objectKey
	p.lastDownloadDst = dst
	body, ok := p.downloadBodies[objectKey]
	if !ok {
		return errors.New("missing downloaded object")
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	return os.WriteFile(dst, body, 0o644)
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

func buildPrepareZipArchive(t *testing.T, entryName string, content string) []byte {
	t.Helper()

	var buf bytes.Buffer
	archive := zip.NewWriter(&buf)
	writer, err := archive.Create(entryName)
	if err != nil {
		t.Fatalf("create archive entry: %v", err)
	}
	if _, err := writer.Write([]byte(content)); err != nil {
		t.Fatalf("write archive entry: %v", err)
	}
	if err := archive.Close(); err != nil {
		t.Fatalf("close archive: %v", err)
	}
	return buf.Bytes()
}
