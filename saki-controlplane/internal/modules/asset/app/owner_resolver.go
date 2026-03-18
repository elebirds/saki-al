package app

import (
	"context"

	"github.com/google/uuid"
)

// ResolvedOwner answers two questions only:
// 1) does the owner exist (nil means not found)
// 2) if owner is a sample, which dataset does it belong to (DatasetID != nil)
type ResolvedOwner struct {
	OwnerType AssetOwnerType
	OwnerID   uuid.UUID
	DatasetID *uuid.UUID
}

type OwnerResolver interface {
	Resolve(ctx context.Context, ownerType AssetOwnerType, ownerID uuid.UUID) (*ResolvedOwner, error)
}
