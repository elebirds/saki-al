package apihttp

import (
	"context"
	"errors"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/google/uuid"
)

type UploadStore interface {
	Init(ctx context.Context, params importrepo.InitUploadSessionParams) (*importrepo.UploadSession, error)
	Get(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
	MarkCompleted(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
	Abort(ctx context.Context, id uuid.UUID) (*importrepo.UploadSession, error)
}

type TaskStore interface {
	Get(ctx context.Context, id uuid.UUID) (*importrepo.ImportTask, error)
	ListEventsAfter(ctx context.Context, taskID uuid.UUID, afterSeq int64, limit int32) ([]importrepo.ImportTaskEvent, error)
}

type PrepareUseCase interface {
	Execute(ctx context.Context, input importapp.PrepareProjectAnnotationsInput) (*importapp.PrepareProjectAnnotationsResult, error)
}

type ExecuteUseCase interface {
	Execute(ctx context.Context, input importapp.ExecuteProjectAnnotationsInput) (*importrepo.ImportTask, error)
}

type Dependencies struct {
	Uploads         UploadStore
	Tasks           TaskStore
	Prepare         PrepareUseCase
	Execute         ExecuteUseCase
	Provider        storage.Provider
	UploadURLExpiry time.Duration
}

type Handlers struct {
	uploads      UploadStore
	tasks        TaskStore
	prepare      PrepareUseCase
	execute      ExecuteUseCase
	provider     storage.Provider
	uploadExpiry time.Duration
}

func NewHandlers(deps Dependencies) *Handlers {
	expiry := deps.UploadURLExpiry
	if expiry <= 0 {
		expiry = 15 * time.Minute
	}
	return &Handlers{
		uploads:      deps.Uploads,
		tasks:        deps.Tasks,
		prepare:      deps.Prepare,
		execute:      deps.Execute,
		provider:     deps.Provider,
		uploadExpiry: expiry,
	}
}

func (h *Handlers) Enabled() bool {
	return h != nil && h.uploads != nil && h.tasks != nil && h.prepare != nil && h.execute != nil && h.provider != nil
}

func (h *Handlers) InitImportUploadSession(ctx context.Context, req *openapi.ImportUploadInitRequest) (*openapi.ImportUploadInitResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	principalID, err := currentPrincipalID(ctx)
	if err != nil {
		return nil, err
	}
	if req.GetMode() != "project_annotations" {
		return nil, badRequest("当前仅支持 project_annotations 导入上传")
	}
	if req.GetResourceType() != "project" {
		return nil, badRequest("当前仅支持 project 资源导入上传")
	}

	objectKey := buildUploadObjectKey(req.GetFilename())
	session, err := h.uploads.Init(ctx, importrepo.InitUploadSessionParams{
		UserID:      principalID,
		Mode:        req.GetMode(),
		FileName:    req.GetFilename(),
		ObjectKey:   objectKey,
		ContentType: req.GetContentType(),
	})
	if err != nil {
		return nil, err
	}
	putURL, err := h.provider.SignPutObject(ctx, session.ObjectKey, h.uploadExpiry, session.ContentType)
	if err != nil {
		return nil, err
	}

	return &openapi.ImportUploadInitResponse{
		SessionID: session.ID.String(),
		Strategy:  "single_put",
		Status:    session.Status,
		ObjectKey: session.ObjectKey,
		URL:       putURL,
		Headers:   openapi.ImportUploadHeaders{},
	}, nil
}

func (h *Handlers) SignImportUploadParts(ctx context.Context, req *openapi.ImportUploadPartSignRequest, params openapi.SignImportUploadPartsParams) (*openapi.ImportUploadPartSignResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	session, err := h.loadOwnedUploadSession(ctx, params.SessionID)
	if err != nil {
		return nil, err
	}

	parts := make([]openapi.ImportUploadPartSignedItem, 0, len(req.GetPartNumbers()))
	return &openapi.ImportUploadPartSignResponse{
		SessionID: session.ID.String(),
		UploadID:  "",
		Parts:     parts,
	}, nil
}

func (h *Handlers) CompleteImportUploadSession(ctx context.Context, req *openapi.ImportUploadCompleteRequest, params openapi.CompleteImportUploadSessionParams) (*openapi.ImportUploadSession, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	session, err := h.loadOwnedUploadSession(ctx, params.SessionID)
	if err != nil {
		return nil, err
	}
	if session.Status != "initiated" {
		return nil, badRequest("上传会话状态不允许 complete")
	}
	info, err := h.provider.StatObject(ctx, session.ObjectKey)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotFound) {
			return nil, badRequest("上传内容不存在")
		}
		return nil, err
	}
	if req.GetSize() > 0 && info.Size != req.GetSize() {
		return nil, badRequest("上传内容大小与 complete 请求不一致")
	}
	session, err = h.uploads.MarkCompleted(ctx, session.ID)
	if err != nil {
		return nil, err
	}
	resp, err := h.toOpenAPIUploadSession(ctx, session)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

func (h *Handlers) AbortImportUploadSession(ctx context.Context, params openapi.AbortImportUploadSessionParams) (*openapi.ImportUploadAbortResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	session, err := h.loadOwnedUploadSession(ctx, params.SessionID)
	if err != nil {
		return nil, err
	}
	session, err = h.uploads.Abort(ctx, session.ID)
	if err != nil {
		return nil, err
	}
	return &openapi.ImportUploadAbortResponse{
		SessionID: session.ID.String(),
		Status:    session.Status,
	}, nil
}

func (h *Handlers) GetImportUploadSession(ctx context.Context, params openapi.GetImportUploadSessionParams) (*openapi.ImportUploadSession, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	session, err := h.loadOwnedUploadSession(ctx, params.SessionID)
	if err != nil {
		return nil, err
	}
	resp, err := h.toOpenAPIUploadSession(ctx, session)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

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
