package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	"github.com/google/uuid"
)

// 项目标注导入流处理 prepare/execute/task 查询，和上传会话流保持边界分离。
func (h *Handlers) PrepareProjectAnnotationImport(ctx context.Context, req *openapi.PrepareProjectAnnotationImportRequest, params openapi.PrepareProjectAnnotationImportParams) (*openapi.PrepareProjectAnnotationImportResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	projectID, err := uuid.Parse(params.ProjectID)
	if err != nil {
		return nil, badRequest("invalid project_id")
	}
	datasetID, err := uuid.Parse(params.DatasetID)
	if err != nil {
		return nil, badRequest("invalid dataset_id")
	}
	uploadSessionID, err := uuid.Parse(req.GetUploadSessionID())
	if err != nil {
		return nil, badRequest("invalid upload_session_id")
	}

	result, err := h.prepare.Execute(ctx, importapp.PrepareProjectAnnotationsInput{
		ProjectID:       projectID,
		DatasetID:       datasetID,
		UploadSessionID: uploadSessionID,
		FormatProfile:   req.GetFormatProfile(),
		Split:           req.GetSplit().Or(""),
	})
	if err != nil {
		return nil, err
	}

	capabilities := openapi.ImportPrepareGeometryCapabilities{
		DetectedGeometryKinds:    make([]string, 0, len(result.GeometryCapabilities.DetectedGeometryKinds)),
		UnsupportedGeometryKinds: make([]string, 0, len(result.GeometryCapabilities.UnsupportedGeometryKinds)),
		ConvertedGeometryCounts:  openapi.ImportPrepareGeometryCapabilitiesConvertedGeometryCounts{},
	}
	for _, kind := range result.GeometryCapabilities.DetectedGeometryKinds {
		capabilities.DetectedGeometryKinds = append(capabilities.DetectedGeometryKinds, string(kind))
	}
	for _, kind := range result.GeometryCapabilities.UnsupportedGeometryKinds {
		capabilities.UnsupportedGeometryKinds = append(capabilities.UnsupportedGeometryKinds, string(kind))
	}
	for key, count := range result.GeometryCapabilities.ConvertedGeometryCounts {
		capabilities.ConvertedGeometryCounts[key] = int32(count)
	}

	return &openapi.PrepareProjectAnnotationImportResponse{
		Summary: openapi.ImportPrepareSummary{
			FormatProfile:          result.Summary.FormatProfile,
			TotalAnnotations:       int32(result.Summary.TotalAnnotations),
			MatchedAnnotations:     int32(result.Summary.MatchedAnnotations),
			UnmatchedAnnotations:   int32(result.Summary.UnmatchedAnnotations),
			MatchedSamples:         int32(result.Summary.MatchedSamples),
			UnsupportedAnnotations: int32(result.Summary.UnsupportedAnnotations),
		},
		Matching: openapi.ImportPrepareMatching{
			MatchedSampleCount:    int32(result.Matching.MatchedSampleCount),
			BasenameFallbackCount: int32(result.Matching.BasenameFallbackCount),
			AmbiguousMatchCount:   int32(result.Matching.AmbiguousMatchCount),
			UnmatchedSampleKeys:   append([]string(nil), result.Matching.UnmatchedSampleKeys...),
		},
		LabelPlan: openapi.ImportPrepareLabelPlan{
			PlannedNewLabels: append([]string(nil), result.LabelPlan.PlannedNewLabels...),
		},
		GeometryCapabilities: capabilities,
		Warnings:             toOpenAPIIssues(result.Warnings),
		Errors:               toOpenAPIIssues(result.Errors),
		PreviewToken:         result.PreviewToken,
	}, nil
}

func (h *Handlers) ExecuteProjectAnnotationImport(ctx context.Context, req *openapi.ExecuteProjectAnnotationImportRequest, params openapi.ExecuteProjectAnnotationImportParams) (*openapi.ImportTaskCreateResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	projectID, err := uuid.Parse(params.ProjectID)
	if err != nil {
		return nil, badRequest("invalid project_id")
	}
	datasetID, err := uuid.Parse(params.DatasetID)
	if err != nil {
		return nil, badRequest("invalid dataset_id")
	}
	principalID, err := currentPrincipalID(ctx)
	if err != nil {
		return nil, err
	}

	task, err := h.execute.Execute(ctx, importapp.ExecuteProjectAnnotationsInput{
		ProjectID:    projectID,
		DatasetID:    datasetID,
		PreviewToken: req.GetPreviewToken(),
		UserID:       principalID,
	})
	if err != nil {
		if err == importapp.ErrBlockingPreviewManifest {
			return nil, badRequest("preview manifest contains blocking errors")
		}
		return nil, err
	}

	return toOpenAPITaskCreate(task), nil
}

func (h *Handlers) GetImportTask(ctx context.Context, params openapi.GetImportTaskParams) (*openapi.ImportTaskStatusResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	task, err := h.loadOwnedTask(ctx, params.TaskID)
	if err != nil {
		return nil, err
	}
	return &openapi.ImportTaskStatusResponse{
		TaskID:       task.ID.String(),
		Status:       task.Status,
		Mode:         task.Mode,
		ResourceType: task.ResourceType,
		ResourceID:   task.ResourceID.String(),
		CreatedAt:    task.CreatedAt,
		UpdatedAt:    task.UpdatedAt,
	}, nil
}

func (h *Handlers) GetImportTaskResult(ctx context.Context, params openapi.GetImportTaskResultParams) (*openapi.ImportTaskResultResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	task, err := h.loadOwnedTask(ctx, params.TaskID)
	if err != nil {
		return nil, err
	}
	result, err := decodeRawObject(task.Result)
	if err != nil {
		return nil, err
	}
	return &openapi.ImportTaskResultResponse{
		TaskID: task.ID.String(),
		Status: task.Status,
		Result: result,
	}, nil
}
