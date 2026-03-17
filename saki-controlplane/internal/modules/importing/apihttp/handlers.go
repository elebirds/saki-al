package apihttp

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	importapp "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/app"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
	"github.com/go-faster/jx"
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
	Uploads UploadStore
	Tasks   TaskStore
	Prepare PrepareUseCase
	Execute ExecuteUseCase
}

type Handlers struct {
	uploads UploadStore
	tasks   TaskStore
	prepare PrepareUseCase
	execute ExecuteUseCase
}

func NewHandlers(deps Dependencies) *Handlers {
	return &Handlers{
		uploads: deps.Uploads,
		tasks:   deps.Tasks,
		prepare: deps.Prepare,
		execute: deps.Execute,
	}
}

func (h *Handlers) Enabled() bool {
	return h != nil && h.uploads != nil && h.tasks != nil && h.prepare != nil && h.execute != nil
}

func (h *Handlers) InitImportUploadSession(ctx context.Context, req *openapi.ImportUploadInitRequest) (*openapi.ImportUploadInitResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}
	userID, err := currentUserID(ctx)
	if err != nil {
		return nil, err
	}
	if req.GetMode() != "project_annotations" {
		return nil, badRequest("当前仅支持 project_annotations 导入上传")
	}
	if req.GetResourceType() != "project" {
		return nil, badRequest("当前仅支持 project 资源导入上传")
	}

	objectKey := filepath.Join(uploadRootDir(), uuid.NewString()+"-"+sanitizeFilename(req.GetFilename()))
	session, err := h.uploads.Init(ctx, importrepo.InitUploadSessionParams{
		UserID:      userID,
		Mode:        req.GetMode(),
		FileName:    req.GetFilename(),
		ObjectKey:   objectKey,
		ContentType: req.GetContentType(),
	})
	if err != nil {
		return nil, err
	}

	return &openapi.ImportUploadInitResponse{
		SessionID: session.ID.String(),
		Strategy:  "single_put",
		Status:    session.Status,
		ObjectKey: session.ObjectKey,
		URL:       uploadContentURL(session.ID),
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
	info, err := os.Stat(session.ObjectKey)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, badRequest("上传内容不存在")
		}
		return nil, err
	}
	if req.GetSize() > 0 && info.Size() != req.GetSize() {
		return nil, badRequest("上传内容大小与 complete 请求不一致")
	}
	session, err = h.uploads.MarkCompleted(ctx, session.ID)
	if err != nil {
		return nil, err
	}
	return toOpenAPIUploadSession(session), nil
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
	_ = os.Remove(session.ObjectKey)
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
	return toOpenAPIUploadSession(session), nil
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
	userID, err := currentUserID(ctx)
	if err != nil {
		return nil, err
	}

	task, err := h.execute.Execute(ctx, importapp.ExecuteProjectAnnotationsInput{
		ProjectID:    projectID,
		DatasetID:    datasetID,
		PreviewToken: req.GetPreviewToken(),
		UserID:       userID,
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

func (h *Handlers) requireEnabled() error {
	if !h.Enabled() {
		return badRequest("import endpoints are not configured")
	}
	return nil
}

func (h *Handlers) loadOwnedUploadSession(ctx context.Context, rawSessionID string) (*importrepo.UploadSession, error) {
	sessionID, err := uuid.Parse(rawSessionID)
	if err != nil {
		return nil, badRequest("invalid session_id")
	}
	userID, err := currentUserID(ctx)
	if err != nil {
		return nil, err
	}
	session, err := h.uploads.Get(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	if session == nil {
		return nil, notFound("upload session not found")
	}
	if session.UserID != userID {
		return nil, forbidden("upload session does not belong to current user")
	}
	return session, nil
}

func (h *Handlers) loadOwnedTask(ctx context.Context, rawTaskID string) (*importrepo.ImportTask, error) {
	taskID, err := uuid.Parse(rawTaskID)
	if err != nil {
		return nil, badRequest("invalid task_id")
	}
	userID, err := currentUserID(ctx)
	if err != nil {
		return nil, err
	}
	task, err := h.tasks.Get(ctx, taskID)
	if err != nil {
		return nil, err
	}
	if task == nil {
		return nil, notFound("import task not found")
	}
	if task.UserID != userID {
		return nil, forbidden("import task does not belong to current user")
	}
	return task, nil
}

func currentUserID(ctx context.Context) (uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return uuid.Nil, unauthorized("authentication required")
	}
	userID, err := uuid.Parse(claims.UserID)
	if err != nil {
		return uuid.Nil, badRequest("import endpoints require UUID user id")
	}
	return userID, nil
}

func toOpenAPIIssues(issues []importapp.PrepareIssue) []openapi.ImportIssue {
	result := make([]openapi.ImportIssue, 0, len(issues))
	for _, issue := range issues {
		result = append(result, openapi.ImportIssue{
			Code:    issue.Code,
			Message: issue.Message,
		})
	}
	return result
}

func toOpenAPIUploadSession(session *importrepo.UploadSession) *openapi.ImportUploadSession {
	response := &openapi.ImportUploadSession{
		SessionID:   session.ID.String(),
		Mode:        session.Mode,
		FileName:    session.FileName,
		ObjectKey:   session.ObjectKey,
		ContentType: session.ContentType,
		Status:      session.Status,
		Strategy:    "single_put",
		URL:         uploadContentURL(session.ID),
	}
	if session.CompletedAt != nil {
		response.CompletedAt.SetTo(*session.CompletedAt)
	}
	if session.AbortedAt != nil {
		response.AbortedAt.SetTo(*session.AbortedAt)
	}
	return response
}

func toOpenAPITaskCreate(task *importrepo.ImportTask) *openapi.ImportTaskCreateResponse {
	taskID := task.ID.String()
	return &openapi.ImportTaskCreateResponse{
		TaskID:    taskID,
		Status:    task.Status,
		StatusURL: "/imports/tasks/" + taskID,
		ResultURL: "/imports/tasks/" + taskID + "/result",
		StreamURL: "/imports/tasks/" + taskID + "/events",
	}
}

func decodeRawObject(raw []byte) (openapi.ImportTaskResultResponseResult, error) {
	if len(raw) == 0 {
		return openapi.ImportTaskResultResponseResult{}, nil
	}
	decoded := map[string]json.RawMessage{}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return nil, fmt.Errorf("decode raw object: %w", err)
	}
	result := openapi.ImportTaskResultResponseResult{}
	for key, value := range decoded {
		result[key] = jx.Raw(value)
	}
	return result, nil
}

func sanitizeFilename(name string) string {
	base := filepath.Base(strings.TrimSpace(name))
	if base == "." || base == string(filepath.Separator) || base == "" {
		return "import.zip"
	}
	replacer := strings.NewReplacer("/", "-", "\\", "-", "\x00", "-")
	return replacer.Replace(base)
}

func uploadRootDir() string {
	return filepath.Join(os.TempDir(), "saki-controlplane-imports")
}

func uploadContentURL(sessionID uuid.UUID) string {
	return "/imports/uploads/" + sessionID.String() + "/content"
}

func parseAfterSeq(raw string) (int64, error) {
	if raw == "" {
		return 0, nil
	}
	return strconv.ParseInt(raw, 10, 64)
}

func unauthorized(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusUnauthorized,
		Response: openapi.ErrorResponse{
			Code:    "unauthorized",
			Message: message,
		},
	}
}

func forbidden(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusForbidden,
		Response: openapi.ErrorResponse{
			Code:    "forbidden",
			Message: message,
		},
	}
}

func badRequest(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusBadRequest,
		Response: openapi.ErrorResponse{
			Code:    "bad_request",
			Message: message,
		},
	}
}

func notFound(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusNotFound,
		Response: openapi.ErrorResponse{
			Code:    "not_found",
			Message: message,
		},
	}
}
