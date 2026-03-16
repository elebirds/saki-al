package app

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"time"

	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	projectrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/project/repo"
	"github.com/google/uuid"
	"github.com/saki-ai/saki/shared/saki-ir/go/formats/common"
	annotationirv1 "github.com/saki-ai/saki/shared/saki-ir/go/gen/annotationirv1"
	"google.golang.org/protobuf/encoding/protojson"
)

type ProjectStore interface {
	GetProject(ctx context.Context, id uuid.UUID) (*projectrepo.Project, error)
}

type UploadSessionStore interface {
	Get(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
}

type PreviewManifestStore interface {
	Put(ctx context.Context, params importrepo.PutPreviewManifestParams) (*importrepo.PreviewManifest, error)
}

type PrepareProjectAnnotationsInput struct {
	ProjectID       uuid.UUID
	UploadSessionID uuid.UUID
	FormatProfile   string
	Split           string
}

type PrepareSummary struct {
	FormatProfile          string `json:"format_profile"`
	TotalAnnotations       int    `json:"total_annotations"`
	MatchedAnnotations     int    `json:"matched_annotations"`
	UnmatchedAnnotations   int    `json:"unmatched_annotations"`
	MatchedSamples         int    `json:"matched_samples"`
	UnsupportedAnnotations int    `json:"unsupported_annotations"`
}

type PrepareMatchingSummary struct {
	MatchedSampleCount    int      `json:"matched_sample_count"`
	BasenameFallbackCount int      `json:"basename_fallback_count"`
	AmbiguousMatchCount   int      `json:"ambiguous_match_count"`
	UnmatchedSampleKeys   []string `json:"unmatched_sample_keys"`
}

type PrepareLabelPlan struct {
	PlannedNewLabels []string `json:"planned_new_labels"`
}

type PrepareGeometryCapabilities struct {
	DetectedGeometryKinds    []common.GeometryKind `json:"detected_geometry_kinds"`
	UnsupportedGeometryKinds []common.GeometryKind `json:"unsupported_geometry_kinds"`
	ConvertedGeometryCounts  map[string]int        `json:"converted_geometry_counts"`
}

type PrepareIssue struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type PrepareProjectAnnotationsResult struct {
	Summary              PrepareSummary              `json:"summary"`
	Matching             PrepareMatchingSummary      `json:"matching"`
	LabelPlan            PrepareLabelPlan            `json:"label_plan"`
	GeometryCapabilities PrepareGeometryCapabilities `json:"geometry_capabilities"`
	Warnings             []PrepareIssue              `json:"warnings"`
	Errors               []PrepareIssue              `json:"errors"`
	PreviewToken         string                      `json:"preview_token"`
}

type PreviewManifest struct {
	Mode               string                   `json:"mode"`
	ProjectID          uuid.UUID                `json:"project_id"`
	UploadSessionID    uuid.UUID                `json:"upload_session_id"`
	FormatProfile      string                   `json:"format_profile"`
	SourcePath         string                   `json:"source_path"`
	Summary            PrepareSummary           `json:"summary"`
	MatchedAnnotations []MatchedAnnotationEntry `json:"matched_annotations"`
	PlannedNewLabels   []string                 `json:"planned_new_labels"`
	Warnings           []PrepareIssue           `json:"warnings"`
	Errors             []PrepareIssue           `json:"errors"`
}

type MatchedAnnotationEntry struct {
	AnnotationID      string          `json:"annotation_id"`
	ResolvedSampleID  uuid.UUID       `json:"resolved_sample_id"`
	SampleRef         string          `json:"sample_ref"`
	GroupID           string          `json:"group_id"`
	LabelID           string          `json:"label_id"`
	LabelName         string          `json:"label_name"`
	View              string          `json:"view"`
	AnnotationType    string          `json:"annotation_type"`
	Geometry          json.RawMessage `json:"geometry"`
	Source            string          `json:"source"`
	InputGeometryKind string          `json:"input_geometry_kind"`
}

type PrepareProjectAnnotationsUseCase struct {
	projects ProjectStore
	uploads  UploadSessionStore
	previews PreviewManifestStore
	matches  SampleMatchFinder
	parsers  ProjectAnnotationParser
}

func NewPrepareProjectAnnotationsUseCase(
	projects ProjectStore,
	uploads UploadSessionStore,
	previews PreviewManifestStore,
	matches SampleMatchFinder,
	parsers ProjectAnnotationParser,
) *PrepareProjectAnnotationsUseCase {
	return &PrepareProjectAnnotationsUseCase{
		projects: projects,
		uploads:  uploads,
		previews: previews,
		matches:  matches,
		parsers:  parsers,
	}
}

func (u *PrepareProjectAnnotationsUseCase) Execute(ctx context.Context, input PrepareProjectAnnotationsInput) (*PrepareProjectAnnotationsResult, error) {
	project, err := u.projects.GetProject(ctx, input.ProjectID)
	if err != nil {
		return nil, err
	}
	if project == nil {
		return nil, errors.New("project not found")
	}

	session, err := u.uploads.Get(ctx, input.UploadSessionID)
	if err != nil {
		return nil, err
	}
	if session == nil {
		return nil, errors.New("upload session not found")
	}
	if session.Status != "completed" {
		return nil, errors.New("upload session is not completed")
	}

	sourcePath, cleanup, err := resolveImportSourcePath(input.FormatProfile, session.ObjectKey)
	if err != nil {
		return nil, err
	}
	defer cleanup()

	parsed, err := u.parsers.ParseProjectAnnotations(ctx, ParseProjectAnnotationsRequest{
		FormatProfile: input.FormatProfile,
		SourcePath:    sourcePath,
		Split:         input.Split,
	})
	if err != nil {
		return nil, err
	}

	labelNames := collectLabelNames(parsed.Batch)
	annotationsByID := indexAnnotations(parsed.Batch)
	labelNamesByID := indexLabelNames(parsed.Batch)

	result := &PrepareProjectAnnotationsResult{
		Summary: PrepareSummary{
			FormatProfile:          input.FormatProfile,
			TotalAnnotations:       len(parsed.Annotations),
			UnsupportedAnnotations: len(parsed.UnsupportedGeometryKinds),
		},
		Matching: PrepareMatchingSummary{
			UnmatchedSampleKeys: make([]string, 0),
		},
		LabelPlan: PrepareLabelPlan{
			PlannedNewLabels: labelNames,
		},
		GeometryCapabilities: PrepareGeometryCapabilities{
			DetectedGeometryKinds:    append([]common.GeometryKind(nil), parsed.DetectedGeometryKinds...),
			UnsupportedGeometryKinds: append([]common.GeometryKind(nil), parsed.UnsupportedGeometryKinds...),
			ConvertedGeometryCounts:  map[string]int{},
		},
		Warnings: make([]PrepareIssue, 0, len(parsed.Report.Warnings)),
		Errors:   make([]PrepareIssue, 0, len(parsed.Report.Errors)),
	}

	for _, warning := range parsed.Report.Warnings {
		result.Warnings = append(result.Warnings, PrepareIssue{Code: warning.Code, Message: warning.Message})
	}
	for _, issue := range parsed.Report.Errors {
		result.Errors = append(result.Errors, PrepareIssue{Code: issue.Code, Message: issue.Message})
	}

	matchedEntries := make([]MatchedAnnotationEntry, 0, len(parsed.Annotations))
	uniqueSamples := map[uuid.UUID]struct{}{}
	for _, parsedAnnotation := range parsed.Annotations {
		decision, err := matchSampleRef(ctx, u.matches, input.ProjectID, parsedAnnotation.PrimarySampleRef)
		if err != nil {
			switch {
			case errors.Is(err, ErrAmbiguousSampleMatch):
				result.Matching.AmbiguousMatchCount++
				result.Errors = append(result.Errors, PrepareIssue{
					Code:    "AMBIGUOUS_SAMPLE_MATCH",
					Message: "样本匹配出现歧义: " + parsedAnnotation.PrimarySampleRef.NormalizedValue,
				})
			case errors.Is(err, ErrSampleNotMatched):
				result.Matching.UnmatchedSampleKeys = append(result.Matching.UnmatchedSampleKeys, parsedAnnotation.PrimarySampleRef.NormalizedValue)
				result.Errors = append(result.Errors, PrepareIssue{
					Code:    "SAMPLE_NOT_MATCHED",
					Message: "未找到样本: " + parsedAnnotation.PrimarySampleRef.NormalizedValue,
				})
			default:
				return nil, err
			}
			continue
		}
		if decision.Warning != nil {
			result.Warnings = append(result.Warnings, PrepareIssue{Code: decision.Warning.Code, Message: decision.Warning.Message})
		}
		if decision.Strategy == "basename" {
			result.Matching.BasenameFallbackCount++
		}

		record := annotationsByID[parsedAnnotation.AnnotationID]
		if record == nil {
			result.Errors = append(result.Errors, PrepareIssue{
				Code:    "ANNOTATION_NOT_FOUND_IN_BATCH",
				Message: "解析结果缺少 annotation " + parsedAnnotation.AnnotationID,
			})
			continue
		}
		geometryJSON, err := protojson.Marshal(record.GetGeometry())
		if err != nil {
			return nil, err
		}

		matchedEntries = append(matchedEntries, MatchedAnnotationEntry{
			AnnotationID:      parsedAnnotation.AnnotationID,
			ResolvedSampleID:  decision.SampleID,
			SampleRef:         parsedAnnotation.PrimarySampleRef.NormalizedValue,
			GroupID:           parsedAnnotation.AnnotationID,
			LabelID:           labelNamesByID[record.GetLabelId()],
			LabelName:         labelNamesByID[record.GetLabelId()],
			View:              "default",
			AnnotationType:    annotationTypeFromGeometry(record.GetGeometry()),
			Geometry:          geometryJSON,
			Source:            "imported",
			InputGeometryKind: string(parsedAnnotation.InputGeometryKind),
		})
		uniqueSamples[decision.SampleID] = struct{}{}
	}

	result.Summary.MatchedAnnotations = len(matchedEntries)
	result.Summary.UnmatchedAnnotations = len(parsed.Annotations) - len(matchedEntries)
	result.Summary.MatchedSamples = len(uniqueSamples)
	result.Matching.MatchedSampleCount = len(uniqueSamples)

	previewToken := uuid.NewString()
	manifest := PreviewManifest{
		Mode:               "project_annotations",
		ProjectID:          input.ProjectID,
		UploadSessionID:    input.UploadSessionID,
		FormatProfile:      input.FormatProfile,
		SourcePath:         session.ObjectKey,
		Summary:            result.Summary,
		MatchedAnnotations: matchedEntries,
		PlannedNewLabels:   result.LabelPlan.PlannedNewLabels,
		Warnings:           append([]PrepareIssue(nil), result.Warnings...),
		Errors:             append([]PrepareIssue(nil), result.Errors...),
	}
	manifestBytes, err := json.Marshal(manifest)
	if err != nil {
		return nil, err
	}
	if _, err := u.previews.Put(ctx, importrepo.PutPreviewManifestParams{
		Token:           previewToken,
		Mode:            manifest.Mode,
		ProjectID:       manifest.ProjectID,
		UploadSessionID: manifest.UploadSessionID,
		Manifest:        manifestBytes,
		ParamsHash:      paramsHash(input, session.ObjectKey),
		ExpiresAt:       time.Now().Add(30 * time.Minute).UTC(),
	}); err != nil {
		return nil, err
	}

	result.PreviewToken = previewToken
	return result, nil
}

func collectLabelNames(batch *annotationirv1.DataBatchIR) []string {
	set := map[string]struct{}{}
	for _, item := range batch.GetItems() {
		if label := item.GetLabel(); label != nil && label.GetName() != "" {
			set[label.GetName()] = struct{}{}
		}
	}
	names := make([]string, 0, len(set))
	for name := range set {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func indexAnnotations(batch *annotationirv1.DataBatchIR) map[string]*annotationirv1.AnnotationRecord {
	records := make(map[string]*annotationirv1.AnnotationRecord, len(batch.GetItems()))
	for _, item := range batch.GetItems() {
		if ann := item.GetAnnotation(); ann != nil {
			records[ann.GetId()] = ann
		}
	}
	return records
}

func indexLabelNames(batch *annotationirv1.DataBatchIR) map[string]string {
	labels := make(map[string]string, len(batch.GetItems()))
	for _, item := range batch.GetItems() {
		if label := item.GetLabel(); label != nil {
			labels[label.GetId()] = label.GetName()
		}
	}
	return labels
}

func annotationTypeFromGeometry(geometry *annotationirv1.Geometry) string {
	if geometry == nil {
		return ""
	}
	switch geometry.GetShape().(type) {
	case *annotationirv1.Geometry_Rect:
		return "rect"
	case *annotationirv1.Geometry_Obb:
		return "obb"
	default:
		return ""
	}
}

func paramsHash(input PrepareProjectAnnotationsInput, sourcePath string) string {
	sum := sha256.Sum256([]byte(input.ProjectID.String() + "|" + input.UploadSessionID.String() + "|" + input.FormatProfile + "|" + input.Split + "|" + sourcePath))
	return hex.EncodeToString(sum[:])
}
