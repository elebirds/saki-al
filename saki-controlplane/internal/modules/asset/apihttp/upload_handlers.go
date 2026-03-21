package apihttp

import (
	"context"
	"errors"
	"strings"
	"time"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	ogenhttp "github.com/ogen-go/ogen/http"
)

// durable upload 写链路负责初始化、完成、取消上传，不处理资产读取与下载。
func (h *Handlers) InitAssetUpload(ctx context.Context, req *openapi.AssetUploadInitRequest) (*openapi.AssetUploadInitResponse, error) {
	if h == nil || h.initUpload == nil {
		return nil, ogenhttp.ErrNotImplemented
	}

	principalID, err := currentPrincipalID(ctx)
	if err != nil {
		return nil, err
	}
	binding, err := parseOwnerBinding(req)
	if err != nil {
		return nil, badRequest(err.Error())
	}
	if err := requireOwnerWritePermission(ctx, binding); err != nil {
		return nil, err
	}
	kind, err := assetapp.ParseAssetKind(normalizeKind(req.GetKind()))
	if err != nil {
		return nil, badRequest("invalid kind")
	}
	metadata, err := encodeMetadata(req.GetMetadata())
	if err != nil {
		return nil, badRequest("invalid metadata")
	}

	result, err := h.initUpload.Execute(ctx, assetapp.InitDurableUploadInput{
		Binding:             binding,
		Kind:                kind,
		DeclaredContentType: strings.TrimSpace(req.GetContentType()),
		Metadata:            metadata,
		IdempotencyKey:      strings.TrimSpace(req.GetIdempotencyKey()),
		CreatedBy:           principalID,
	})
	if err != nil {
		return nil, mapInitError(err)
	}
	if result == nil || result.Asset == nil || result.Intent == nil {
		return nil, errors.New("asset init result is incomplete")
	}

	resp := &openapi.AssetUploadInitResponse{
		Asset:       *toOpenAPIAsset(result.Asset),
		IntentState: toOpenAPIInitIntentState(result.Intent.State),
	}
	if result.UploadTicket != nil {
		resp.UploadURL.SetTo(result.UploadTicket.URL)
		resp.ExpiresIn.SetTo(int32(h.uploadExpiry / time.Second))
	} else {
		resp.UploadURL.SetToNull()
		resp.ExpiresIn.SetToNull()
	}
	return resp, nil
}

func (h *Handlers) CompleteAssetUpload(ctx context.Context, req *openapi.AssetCompleteRequest, params openapi.CompleteAssetUploadParams) (*openapi.Asset, error) {
	if h == nil || h.completeUpload == nil || h.intentStore == nil {
		return nil, ogenhttp.ErrNotImplemented
	}

	assetID, err := parseAssetID(params.AssetID)
	if err != nil {
		return nil, badRequest(err.Error())
	}
	intent, err := h.intentStore.GetUploadIntentByAssetID(ctx, assetID)
	if err != nil {
		return nil, err
	}
	if intent == nil {
		return nil, notFound("asset not found")
	}
	if err := requireOwnerWritePermission(ctx, intent.Binding); err != nil {
		return nil, err
	}

	input := assetapp.CompleteDurableUploadInput{AssetID: assetID}
	if sizeBytes, ok := req.SizeBytes.Get(); ok {
		input.RequestSizeBytes = &sizeBytes
	}
	if raw, ok := req.GetSHA256Hex().Get(); ok {
		raw = strings.TrimSpace(raw)
		if raw != "" {
			input.SHA256Hex = &raw
		}
	}

	result, err := h.completeUpload.Execute(ctx, input)
	if err != nil {
		return nil, mapCompleteError(err)
	}
	if result == nil || result.Asset == nil {
		return nil, errors.New("asset complete result is incomplete")
	}
	return toOpenAPIAsset(result.Asset), nil
}

func (h *Handlers) CancelAssetUpload(ctx context.Context, params openapi.CancelAssetUploadParams) (*openapi.AssetUploadCancelResponse, error) {
	if h == nil || h.cancelUpload == nil || h.intentStore == nil {
		return nil, ogenhttp.ErrNotImplemented
	}

	assetID, err := parseAssetID(params.AssetID)
	if err != nil {
		return nil, badRequest(err.Error())
	}
	intent, err := h.intentStore.GetUploadIntentByAssetID(ctx, assetID)
	if err != nil {
		return nil, err
	}
	if intent == nil {
		return nil, notFound("asset not found")
	}
	if err := requireOwnerWritePermission(ctx, intent.Binding); err != nil {
		return nil, err
	}

	result, err := h.cancelUpload.Execute(ctx, assetID)
	if err != nil {
		return nil, mapCancelError(err)
	}
	if result == nil || result.Intent == nil {
		return nil, errors.New("asset cancel result is incomplete")
	}
	return &openapi.AssetUploadCancelResponse{
		AssetID:     result.Intent.AssetID,
		IntentState: toOpenAPICancelIntentState(result.Intent.State),
	}, nil
}
