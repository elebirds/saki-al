package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	ogenhttp "github.com/ogen-go/ogen/http"
)

// 资产与导入共享“能力开关”边界：未启用时统一回 `ErrNotImplemented`，保持旧行为。
func (s *Server) InitAssetUpload(ctx context.Context, req *openapi.AssetUploadInitRequest) (*openapi.AssetUploadInitResponse, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.InitAssetUpload(ctx, req)
}

func (s *Server) CancelAssetUpload(ctx context.Context, params openapi.CancelAssetUploadParams) (*openapi.AssetUploadCancelResponse, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.CancelAssetUpload(ctx, params)
}

func (s *Server) CompleteAssetUpload(ctx context.Context, req *openapi.AssetCompleteRequest, params openapi.CompleteAssetUploadParams) (*openapi.Asset, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.CompleteAssetUpload(ctx, req, params)
}

func (s *Server) GetAsset(ctx context.Context, params openapi.GetAssetParams) (*openapi.Asset, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.GetAsset(ctx, params)
}

func (s *Server) SignAssetDownload(ctx context.Context, req *openapi.AssetDownloadSignRequest, params openapi.SignAssetDownloadParams) (*openapi.AssetDownloadSignResponse, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.SignAssetDownload(ctx, req, params)
}

func (s *Server) InitImportUploadSession(ctx context.Context, req *openapi.ImportUploadInitRequest) (*openapi.ImportUploadInitResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.InitImportUploadSession(ctx, req)
}

func (s *Server) SignImportUploadParts(ctx context.Context, req *openapi.ImportUploadPartSignRequest, params openapi.SignImportUploadPartsParams) (*openapi.ImportUploadPartSignResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.SignImportUploadParts(ctx, req, params)
}

func (s *Server) CompleteImportUploadSession(ctx context.Context, req *openapi.ImportUploadCompleteRequest, params openapi.CompleteImportUploadSessionParams) (*openapi.ImportUploadSession, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.CompleteImportUploadSession(ctx, req, params)
}

func (s *Server) AbortImportUploadSession(ctx context.Context, params openapi.AbortImportUploadSessionParams) (*openapi.ImportUploadAbortResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.AbortImportUploadSession(ctx, params)
}

func (s *Server) GetImportUploadSession(ctx context.Context, params openapi.GetImportUploadSessionParams) (*openapi.ImportUploadSession, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.GetImportUploadSession(ctx, params)
}

func (s *Server) PrepareProjectAnnotationImport(ctx context.Context, req *openapi.PrepareProjectAnnotationImportRequest, params openapi.PrepareProjectAnnotationImportParams) (*openapi.PrepareProjectAnnotationImportResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.PrepareProjectAnnotationImport(ctx, req, params)
}

func (s *Server) ExecuteProjectAnnotationImport(ctx context.Context, req *openapi.ExecuteProjectAnnotationImportRequest, params openapi.ExecuteProjectAnnotationImportParams) (*openapi.ImportTaskCreateResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.ExecuteProjectAnnotationImport(ctx, req, params)
}

func (s *Server) GetImportTask(ctx context.Context, params openapi.GetImportTaskParams) (*openapi.ImportTaskStatusResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.GetImportTask(ctx, params)
}

func (s *Server) GetImportTaskResult(ctx context.Context, params openapi.GetImportTaskResultParams) (*openapi.ImportTaskResultResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.GetImportTaskResult(ctx, params)
}
