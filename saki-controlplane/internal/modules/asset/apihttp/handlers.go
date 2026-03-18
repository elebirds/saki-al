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
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	assetrepo "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/repo"
	"github.com/go-faster/jx"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type Store interface {
	CreatePending(ctx context.Context, params assetrepo.CreatePendingParams) (*assetrepo.Asset, error)
	Get(ctx context.Context, id uuid.UUID) (*assetrepo.Asset, error)
	MarkReady(ctx context.Context, params assetrepo.MarkReadyParams) (*assetrepo.Asset, error)
}

type Dependencies struct {
	Store           Store
	Provider        storage.Provider
	UploadURLExpiry time.Duration
	DownloadExpiry  time.Duration
}

type Handlers struct {
	store          Store
	provider       storage.Provider
	uploadExpiry   time.Duration
	downloadExpiry time.Duration
}

func NewHandlers(deps Dependencies) *Handlers {
	return &Handlers{
		store:          deps.Store,
		provider:       deps.Provider,
		uploadExpiry:   deps.UploadURLExpiry,
		downloadExpiry: deps.DownloadExpiry,
	}
}

func (h *Handlers) Enabled() bool {
	return h != nil && h.store != nil && h.provider != nil
}

func (h *Handlers) InitAssetUpload(ctx context.Context, req *openapi.AssetUploadInitRequest) (*openapi.AssetUploadInitResponse, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
	}

	userID, err := currentUserID(ctx)
	if err != nil {
		return nil, err
	}
	kind := normalizeKind(req.GetKind())
	if kind == "" {
		return nil, badRequest("invalid kind")
	}
	metadata, err := encodeMetadata(req.GetMetadata())
	if err != nil {
		return nil, badRequest("invalid metadata")
	}

	created, err := h.store.CreatePending(ctx, assetrepo.CreatePendingParams{
		Kind:           kind,
		StorageBackend: "minio",
		Bucket:         h.provider.Bucket(),
		ObjectKey:      buildObjectKey(kind),
		ContentType:    strings.TrimSpace(req.GetContentType()),
		Metadata:       metadata,
		CreatedBy:      &userID,
	})
	if err != nil {
		return nil, err
	}

	ticket, err := assetapp.NewIssueUploadTicketUseCase(h.store, h.provider, h.uploadExpiry).Execute(ctx, created.ID)
	if err != nil {
		return nil, err
	}

	return &openapi.AssetUploadInitResponse{
		Asset:     *toOpenAPIAsset(created),
		UploadURL: ticket.URL,
		ExpiresIn: int32(h.uploadExpiry / time.Second),
		Headers:   openapi.NewOptAssetUploadHeaders(openapi.AssetUploadHeaders{}),
	}, nil
}

func (h *Handlers) CompleteAssetUpload(ctx context.Context, req *openapi.AssetCompleteRequest, params openapi.CompleteAssetUploadParams) (*openapi.Asset, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
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
	if asset.Status != assetrepo.AssetStatusPendingUpload {
		return nil, badRequest("asset is not pending upload")
	}

	stat, err := h.provider.StatObject(ctx, asset.ObjectKey)
	if err != nil {
		if errors.Is(err, storage.ErrObjectNotFound) {
			return nil, badRequest("uploaded object not found")
		}
		return nil, err
	}
	if sizeBytes, ok := req.SizeBytes.Get(); ok && stat.Size != sizeBytes {
		return nil, badRequest("size_bytes does not match uploaded object")
	}

	contentType := asset.ContentType
	if stat.ContentType != "" {
		contentType = stat.ContentType
	}

	var sha256Hex *string
	if raw, ok := req.GetSHA256Hex().Get(); ok {
		raw = strings.TrimSpace(raw)
		if raw != "" {
			sha256Hex = &raw
		}
	}

	updated, err := h.store.MarkReady(ctx, assetrepo.MarkReadyParams{
		ID:          asset.ID,
		SizeBytes:   stat.Size,
		Sha256Hex:   sha256Hex,
		ContentType: contentType,
	})
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, badRequest("asset is not pending upload")
	}
	return toOpenAPIAsset(updated), nil
}

func (h *Handlers) GetAsset(ctx context.Context, params openapi.GetAssetParams) (*openapi.Asset, error) {
	if err := h.requireEnabled(); err != nil {
		return nil, err
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
	if err := h.requireEnabled(); err != nil {
		return nil, err
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

func (h *Handlers) requireEnabled() error {
	if !h.Enabled() {
		return ogenhttp.ErrNotImplemented
	}
	return nil
}

func currentUserID(ctx context.Context) (uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return uuid.Nil, unauthorized("authentication required")
	}
	userID, err := uuid.Parse(claims.UserID)
	if err != nil {
		return uuid.Nil, badRequest("asset endpoints require UUID user id")
	}
	return userID, nil
}

func parseAssetID(raw string) (uuid.UUID, error) {
	assetID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid asset_id")
	}
	return assetID, nil
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

func buildObjectKey(kind string) string {
	return kind + "/" + uuid.NewString()
}

func encodeMetadata(metadata map[string]jx.Raw) ([]byte, error) {
	if len(metadata) == 0 {
		return []byte(`{}`), nil
	}
	return json.Marshal(metadata)
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

func toOpenAPIAsset(asset *assetrepo.Asset) *openapi.Asset {
	if asset == nil {
		return nil
	}

	metadata, err := decodeMetadata(asset.Metadata)
	if err != nil {
		metadata = map[string]jx.Raw{}
	}

	result := &openapi.Asset{
		ID:             asset.ID.String(),
		Kind:           asset.Kind,
		Status:         asset.Status,
		StorageBackend: asset.StorageBackend,
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

func unauthorized(message string) error {
	return &openapi.ErrorResponseStatusCode{
		StatusCode: http.StatusUnauthorized,
		Response: openapi.ErrorResponse{
			Code:    "unauthorized",
			Message: message,
		},
	}
}
