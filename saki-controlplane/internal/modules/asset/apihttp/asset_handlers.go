package apihttp

import (
	"context"
	"errors"
	"time"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	ogenhttp "github.com/ogen-go/ogen/http"
)

// 资产读取流负责资产查询与下载票据签发，不承担上传状态迁移。
func (h *Handlers) GetAsset(ctx context.Context, params openapi.GetAssetParams) (*openapi.Asset, error) {
	if h == nil || h.store == nil {
		return nil, ogenhttp.ErrNotImplemented
	}

	assetID, err := parseAssetID(params.AssetID)
	if err != nil {
		return nil, badRequest(err.Error())
	}
	asset, err := h.store.Get(ctx, assetID)
	if err != nil {
		return nil, err
	}
	if asset == nil {
		return nil, notFound("asset not found")
	}
	return toOpenAPIAsset(asset), nil
}

func (h *Handlers) SignAssetDownload(ctx context.Context, req *openapi.AssetDownloadSignRequest, params openapi.SignAssetDownloadParams) (*openapi.AssetDownloadSignResponse, error) {
	if h == nil || h.store == nil || h.provider == nil {
		return nil, ogenhttp.ErrNotImplemented
	}

	assetID, err := parseAssetID(params.AssetID)
	if err != nil {
		return nil, badRequest(err.Error())
	}

	ticket, err := assetapp.NewIssueDownloadTicketUseCase(h.store, h.provider, h.downloadExpiry).Execute(ctx, assetID)
	if err != nil {
		switch {
		case errors.Is(err, assetapp.ErrAssetNotFound):
			return nil, notFound("asset not found")
		case errors.Is(err, assetapp.ErrAssetNotReady), errors.Is(err, assetapp.ErrAssetBucketMismatch):
			return nil, badRequest(err.Error())
		default:
			return nil, err
		}
	}

	return &openapi.AssetDownloadSignResponse{
		AssetID:     ticket.AssetID.String(),
		DownloadURL: ticket.URL,
		ExpiresIn:   int32(h.downloadExpiry / time.Second),
	}, nil
}
