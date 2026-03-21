package apihttp

import (
	"context"
	"errors"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	importrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/repo"
)

// 上传会话流只负责 import 文件的上传编排，不承担具体导入任务的预处理与执行语义。
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
