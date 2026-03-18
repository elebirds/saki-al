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
	AssetUploadIntentStateInitiated AssetUploadIntentState = "initiated"
	AssetUploadIntentStateCompleted AssetUploadIntentState = "completed"
	AssetUploadIntentStateCanceled  AssetUploadIntentState = "canceled"
	AssetUploadIntentStateExpired   AssetUploadIntentState = "expired"
)

var (
	ErrUnsupportedAssetOwnerType  = errors.New("unsupported asset owner type")
	ErrAssetOwnerIDRequired       = errors.New("asset owner id required")
	ErrInvalidDurableOwnerBinding = errors.New("invalid durable owner binding")
)

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
