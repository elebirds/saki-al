package app

import (
	"errors"

	"github.com/google/uuid"
)

// Typed enums. Values are aligned with DB/sqlc enums.
type AssetKind string
type AssetStatus string
type AssetStorageBackend string
type AssetOwnerType string
type AssetReferenceRole string
type AssetReferenceLifecycle string
type AssetUploadIntentState string

const (
	AssetKindImage    AssetKind = "image"
	AssetKindVideo    AssetKind = "video"
	AssetKindArchive  AssetKind = "archive"
	AssetKindDocument AssetKind = "document"
	AssetKindBinary   AssetKind = "binary"
)

const (
	AssetStatusPendingUpload AssetStatus = "pending_upload"
	AssetStatusReady         AssetStatus = "ready"
)

const (
	AssetStorageBackendMinio AssetStorageBackend = "minio"
)

const (
	AssetOwnerTypeProject AssetOwnerType = "project"
	AssetOwnerTypeDataset AssetOwnerType = "dataset"
	AssetOwnerTypeSample  AssetOwnerType = "sample"
)

const (
	AssetReferenceRoleAttachment AssetReferenceRole = "attachment"
	AssetReferenceRolePrimary    AssetReferenceRole = "primary"
)

const (
	AssetReferenceLifecycleDurable AssetReferenceLifecycle = "durable"
)

const (
	AssetUploadIntentStateInitiated AssetUploadIntentState = "initiated"
	AssetUploadIntentStateCompleted AssetUploadIntentState = "completed"
	AssetUploadIntentStateCanceled  AssetUploadIntentState = "canceled"
	AssetUploadIntentStateExpired   AssetUploadIntentState = "expired"
)

var (
	ErrUnsupportedAssetOwnerType  = errors.New("unsupported asset owner type")
	ErrAssetOwnerIDRequired       = errors.New("asset owner id required")
	ErrInvalidDurableOwnerBinding = errors.New("invalid durable owner binding")
	ErrInvalidAssetKind           = errors.New("invalid asset kind")
	ErrInvalidAssetStatus         = errors.New("invalid asset status")
	ErrInvalidAssetStorageBackend = errors.New("invalid asset storage backend")
	ErrInvalidAssetReferenceRole  = errors.New("invalid asset reference role")
	ErrInvalidAssetLifecycle      = errors.New("invalid asset lifecycle")
	ErrInvalidAssetIntentState    = errors.New("invalid asset upload intent state")
)

func ParseAssetKind(raw string) (AssetKind, error) {
	kind := AssetKind(raw)
	switch kind {
	case AssetKindImage, AssetKindVideo, AssetKindArchive, AssetKindDocument, AssetKindBinary:
		return kind, nil
	default:
		return "", ErrInvalidAssetKind
	}
}

func ParseAssetStatus(raw string) (AssetStatus, error) {
	status := AssetStatus(raw)
	switch status {
	case AssetStatusPendingUpload, AssetStatusReady:
		return status, nil
	default:
		return "", ErrInvalidAssetStatus
	}
}

func ParseAssetStorageBackend(raw string) (AssetStorageBackend, error) {
	backend := AssetStorageBackend(raw)
	switch backend {
	case AssetStorageBackendMinio:
		return backend, nil
	default:
		return "", ErrInvalidAssetStorageBackend
	}
}

func ParseAssetOwnerType(raw string) (AssetOwnerType, error) {
	ownerType := AssetOwnerType(raw)
	switch ownerType {
	case AssetOwnerTypeProject, AssetOwnerTypeDataset, AssetOwnerTypeSample:
		return ownerType, nil
	default:
		return "", ErrUnsupportedAssetOwnerType
	}
}

func ParseAssetReferenceRole(raw string) (AssetReferenceRole, error) {
	role := AssetReferenceRole(raw)
	switch role {
	case AssetReferenceRoleAttachment, AssetReferenceRolePrimary:
		return role, nil
	default:
		return "", ErrInvalidAssetReferenceRole
	}
}

func ParseAssetReferenceLifecycle(raw string) (AssetReferenceLifecycle, error) {
	lifecycle := AssetReferenceLifecycle(raw)
	switch lifecycle {
	case AssetReferenceLifecycleDurable:
		return lifecycle, nil
	default:
		return "", ErrInvalidAssetLifecycle
	}
}

func ParseAssetUploadIntentState(raw string) (AssetUploadIntentState, error) {
	state := AssetUploadIntentState(raw)
	switch state {
	case AssetUploadIntentStateInitiated, AssetUploadIntentStateCompleted, AssetUploadIntentStateCanceled, AssetUploadIntentStateExpired:
		return state, nil
	default:
		return "", ErrInvalidAssetIntentState
	}
}

// DurableOwnerBinding is a validated, typed representation of (owner_type,
// owner_id, role, is_primary). It is intended for durable references (persisted).
type DurableOwnerBinding struct {
	OwnerType AssetOwnerType
	OwnerID   uuid.UUID
	Role      AssetReferenceRole
	IsPrimary bool
}

func (b DurableOwnerBinding) Validate() error {
	switch b.OwnerType {
	case AssetOwnerTypeProject, AssetOwnerTypeDataset, AssetOwnerTypeSample:
		// ok
	default:
		return ErrUnsupportedAssetOwnerType
	}

	if b.OwnerID == uuid.Nil {
		return ErrAssetOwnerIDRequired
	}

	switch b.OwnerType {
	case AssetOwnerTypeProject, AssetOwnerTypeDataset:
		// project|dataset only allow attachment, primary flag can be true/false.
		if b.Role != AssetReferenceRoleAttachment {
			return ErrInvalidDurableOwnerBinding
		}
		return nil
	case AssetOwnerTypeSample:
		// sample:
		// - primary role must have is_primary=true
		// - attachment role must have is_primary=false
		switch b.Role {
		case AssetReferenceRolePrimary:
			if !b.IsPrimary {
				return ErrInvalidDurableOwnerBinding
			}
			return nil
		case AssetReferenceRoleAttachment:
			if b.IsPrimary {
				return ErrInvalidDurableOwnerBinding
			}
			return nil
		default:
			return ErrInvalidDurableOwnerBinding
		}
	default:
		// unreachable due to owner type check above
		return ErrUnsupportedAssetOwnerType
	}
}
