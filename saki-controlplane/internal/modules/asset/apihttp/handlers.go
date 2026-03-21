package apihttp

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type Store = assetapp.Store

type InitUploadUseCase interface {
	Execute(ctx context.Context, input assetapp.InitDurableUploadInput) (*assetapp.InitDurableUploadResult, error)
}

type CompleteUploadUseCase interface {
	Execute(ctx context.Context, input assetapp.CompleteDurableUploadInput) (*assetapp.CompleteDurableUploadResult, error)
}

type CancelUploadUseCase interface {
	Execute(ctx context.Context, assetID uuid.UUID) (*assetapp.CancelDurableUploadResult, error)
}

type Dependencies struct {
	Store           Store
	IntentStore     assetapp.IntentStore
	InitUpload      InitUploadUseCase
	CompleteUpload  CompleteUploadUseCase
	CancelUpload    CancelUploadUseCase
	Provider        storage.Provider
	UploadURLExpiry time.Duration
	DownloadExpiry  time.Duration
}

type Handlers struct {
	store          Store
	intentStore    assetapp.IntentStore
	initUpload     InitUploadUseCase
	completeUpload CompleteUploadUseCase
	cancelUpload   CancelUploadUseCase
	provider       storage.Provider
	uploadExpiry   time.Duration
	downloadExpiry time.Duration
}

func NewHandlers(deps Dependencies) *Handlers {
	return &Handlers{
		store:          deps.Store,
		intentStore:    deps.IntentStore,
		initUpload:     deps.InitUpload,
		completeUpload: deps.CompleteUpload,
		cancelUpload:   deps.CancelUpload,
		provider:       deps.Provider,
		uploadExpiry:   deps.UploadURLExpiry,
		downloadExpiry: deps.DownloadExpiry,
	}
}

func (h *Handlers) Enabled() bool {
	return h != nil && h.store != nil && h.provider != nil
}

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
