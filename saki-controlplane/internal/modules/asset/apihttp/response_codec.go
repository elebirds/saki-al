package apihttp

import (
	"errors"
	"net/http"

	"github.com/elebirds/saki/saki-controlplane/internal/app/storage"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	"github.com/go-faster/jx"
)

// 关键设计：OpenAPI 映射与 HTTP 错误翻译停留在 transport 层，避免业务层反向依赖协议细节。
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
