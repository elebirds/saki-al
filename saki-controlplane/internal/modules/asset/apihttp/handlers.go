package apihttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	"github.com/go-faster/jx"
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

	userID, err := currentUserID(ctx)
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
		CreatedBy:           userID,
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

func currentUserID(ctx context.Context) (*uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, unauthorized("authentication required")
	}
	userID, err := uuid.Parse(claims.UserID)
	if err != nil {
		return nil, nil
	}
	return &userID, nil
}

func parseAssetID(raw string) (uuid.UUID, error) {
	assetID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid asset_id")
	}
	return assetID, nil
}

func parseOwnerBinding(req *openapi.AssetUploadInitRequest) (assetapp.DurableOwnerBinding, error) {
	ownerType, err := assetapp.ParseAssetOwnerType(strings.TrimSpace(string(req.GetOwnerType())))
	if err != nil {
		return assetapp.DurableOwnerBinding{}, err
	}
	role, err := assetapp.ParseAssetReferenceRole(strings.TrimSpace(string(req.GetRole())))
	if err != nil {
		return assetapp.DurableOwnerBinding{}, err
	}
	return assetapp.DurableOwnerBinding{
		OwnerType: ownerType,
		OwnerID:   req.GetOwnerID(),
		Role:      role,
		IsPrimary: req.GetIsPrimary(),
	}, nil
}

func requireOwnerWritePermission(ctx context.Context, binding assetapp.DurableOwnerBinding) error {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return unauthorized("authentication required")
	}
	permission := writePermissionForOwner(binding.OwnerType)
	if permission == "" {
		return accessapp.ErrForbidden
	}
	if !claims.HasPermission(permission) {
		return accessapp.ErrForbidden
	}
	return nil
}

func writePermissionForOwner(ownerType assetapp.AssetOwnerType) string {
	switch ownerType {
	case assetapp.AssetOwnerTypeProject:
		return "projects:write"
	case assetapp.AssetOwnerTypeDataset, assetapp.AssetOwnerTypeSample:
		return "datasets:write"
	default:
		return ""
	}
}

func normalizeKind(raw string) string {
	trimmed := strings.ToLower(strings.TrimSpace(raw))
	if trimmed == "" {
		return ""
	}

	var b strings.Builder
	for _, r := range trimmed {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
		case r >= '0' && r <= '9':
			b.WriteRune(r)
		case r == '-' || r == '_':
			b.WriteRune(r)
		default:
			b.WriteByte('-')
		}
	}
	return strings.Trim(b.String(), "-")
}

func encodeMetadata(metadata map[string]jx.Raw) ([]byte, error) {
	if len(metadata) == 0 {
		return []byte(`{}`), nil
	}
	encoded := make(map[string]json.RawMessage, len(metadata))
	for key, value := range metadata {
		encoded[key] = json.RawMessage(value)
	}
	return json.Marshal(encoded)
}

func decodeMetadata(raw []byte) (map[string]jx.Raw, error) {
	if len(raw) == 0 {
		return map[string]jx.Raw{}, nil
	}
	decoded := map[string]json.RawMessage{}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return nil, err
	}
	result := make(map[string]jx.Raw, len(decoded))
	for key, value := range decoded {
		result[key] = jx.Raw(value)
	}
	return result, nil
}

func toOpenAPIAsset(asset *assetapp.Asset) *openapi.Asset {
	if asset == nil {
		return nil
	}

	metadata, err := decodeMetadata(asset.Metadata)
	if err != nil {
		metadata = map[string]jx.Raw{}
	}

	result := &openapi.Asset{
		ID:             asset.ID.String(),
		Kind:           string(asset.Kind),
		Status:         string(asset.Status),
		StorageBackend: string(asset.StorageBackend),
		Bucket:         asset.Bucket,
		ObjectKey:      asset.ObjectKey,
		ContentType:    asset.ContentType,
		SizeBytes:      asset.SizeBytes,
		Metadata:       metadata,
	}
	if asset.Sha256Hex != nil {
		result.SHA256Hex.SetTo(*asset.Sha256Hex)
	}
	return result
}

func toOpenAPIInitIntentState(state assetapp.AssetUploadIntentState) openapi.AssetUploadInitResponseIntentState {
	switch state {
	case assetapp.AssetUploadIntentStateInitiated:
		return openapi.AssetUploadInitResponseIntentStateInitiated
	case assetapp.AssetUploadIntentStateCompleted:
		return openapi.AssetUploadInitResponseIntentStateCompleted
	case assetapp.AssetUploadIntentStateCanceled:
		return openapi.AssetUploadInitResponseIntentStateCanceled
	default:
		return openapi.AssetUploadInitResponseIntentStateExpired
	}
}

func toOpenAPICancelIntentState(state assetapp.AssetUploadIntentState) openapi.AssetUploadCancelResponseIntentState {
	switch state {
	case assetapp.AssetUploadIntentStateInitiated:
		return openapi.AssetUploadCancelResponseIntentStateInitiated
	case assetapp.AssetUploadIntentStateCompleted:
		return openapi.AssetUploadCancelResponseIntentStateCompleted
	case assetapp.AssetUploadIntentStateCanceled:
		return openapi.AssetUploadCancelResponseIntentStateCanceled
	default:
		return openapi.AssetUploadCancelResponseIntentStateExpired
	}
}

func mapInitError(err error) error {
	switch {
	case errors.Is(err, assetapp.ErrAssetOwnerNotFound):
		return notFound("asset owner not found")
	case errors.Is(err, assetapp.ErrUnsupportedAssetOwnerType),
		errors.Is(err, assetapp.ErrAssetOwnerIDRequired),
		errors.Is(err, assetapp.ErrInvalidDurableOwnerBinding),
		errors.Is(err, assetapp.ErrInvalidAssetKind):
		return badRequest(err.Error())
	case errors.Is(err, assetapp.ErrAssetUploadIdempotencyConflict),
		errors.Is(err, assetapp.ErrAssetUploadIntentConflict):
		return conflict(err.Error())
	default:
		return err
	}
}

func mapCompleteError(err error) error {
	switch {
	case errors.Is(err, assetapp.ErrAssetNotFound):
		return notFound("asset not found")
	case errors.Is(err, assetapp.ErrAssetOwnerNotFound):
		return notFound("asset owner not found")
	case errors.Is(err, storage.ErrObjectNotFound):
		return badRequest("uploaded object not found")
	case errors.Is(err, assetapp.ErrAssetUploadObjectSizeMismatch),
		errors.Is(err, assetapp.ErrAssetBucketMismatch):
		return badRequest(err.Error())
	case errors.Is(err, assetapp.ErrAssetUploadIntentExpired),
		errors.Is(err, assetapp.ErrAssetUploadIntentNotCompletable),
		errors.Is(err, assetapp.ErrDurableReferenceConflict):
		return conflict(err.Error())
	default:
		return err
	}
}

func mapCancelError(err error) error {
	switch {
	case errors.Is(err, assetapp.ErrAssetNotFound):
		return notFound("asset not found")
	case errors.Is(err, assetapp.ErrAssetUploadIntentNotCancelable):
		return conflict(err.Error())
	default:
		return err
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

func conflict(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusConflict,
		Response: openapi.ErrorResponse{
			Code:    "conflict",
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

func unauthorized(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusUnauthorized,
		Response: openapi.ErrorResponse{
			Code:    "unauthorized",
			Message: message,
		},
	}
}
